from ConfigParser import ConfigParser
from io import StringIO
from functools import wraps
from greplin import scales
from celery.bin.base import Command
import collections
import json
import logging
import thread
import threading
import time
import zbxsend


log = logging.getLogger(__name__)
stats = scales.collection(
    '/celery',
    scales.IntStat('started'),

    scales.IntStat('succeeded'),
    scales.IntStat('failed'),
    scales.IntStat('retried'),

    scales.PmfStat('queuetime'),
    scales.PmfStat('runtime'),
)
stats_queue = type('Stats:queues', (object,), {})()
scales._Stats.initChild(stats_queue, 'queues', '', stats)


def task_handler(fn):
    @wraps(fn)
    def wrapper(self, event):
        self.state.event(event)
        task = self.state.tasks.get(event['uuid'])
        return fn(self, event, task)
    return wrapper


class Receiver(object):

    def __init__(self, app):
        self.app = app

    @task_handler
    def on_task_started(self, event, task):
        # XXX We'd like to maybe differentiate this by queue, but
        # task.routing_key is always None, even though in redis it contains the
        # queue name.
        log.debug('Started %s', task)
        stats.started += 1
        if task.sent:
            stats.queuetime = time.time() - task.sent

    @task_handler
    def on_task_succeeded(self, event, task):
        log.debug('Succeeded %s', task)
        stats.succeeded += 1
        if task is not None and task.runtime is not None:
            stats.runtime = task.runtime

    @task_handler
    def on_task_failed(self, event, task):
        log.debug('Failed %s', task)
        stats.failed += 1
        if task is not None and task.runtime is not None:
            stats.runtime = task.runtime

    @task_handler
    def on_task_retried(self, event, task):
        log.debug('Retried %s', task)
        stats.retried += 1
        if task is not None and task.runtime is not None:
            stats.runtime = task.runtime

    def __call__(self, *args, **kw):
        self.state = self.app.events.State()
        kw.setdefault('wakeup', False)

        with self.app.connection() as connection:
            recv = self.app.events.Receiver(connection, handlers={
                'task-started': self.on_task_started,
                'task-succeeded': self.on_task_succeeded,
                'task-failed': self.on_task_failed,
                'task-retried': self.on_task_retried,
                '*': self.state.event,
            })
            recv.capture(*args, **kw)


class Command(Command):

    should_stop = False

    def dump_stats(self):
        while not self.should_stop:
            try:
                data = scales.getStats()['celery']
                log.debug(data)
                metrics = {
                    'celery.task.' + x: data.get(x, 0)
                    for x in ['started', 'succeeded', 'failed', 'retried']
                }
                metrics['celery.task.runtime'] = data.get(
                    'runtime', {}).get('median', -1)
                metrics['celery.task.queuetime'] = data.get(
                    'queuetime', {}).get('median', -1)
                discovery = []
                for key, value in data['queues'].items():
                    metrics['celery.queue[%s]' % key] = value
                    discovery.append({'{#QUEUENAME}': key})
                # See <https://www.zabbix.com/documentation/3.0/manual/
                #   /discovery/low_level_discovery#creating_custom_lld_rules>
                # and <https://github.com/jbfavre/python-protobix/blob/1.0.1
                #   /protobix/datacontainer.py#L53>
                metrics['celery.discover.queues'] = json.dumps(
                    {'data': discovery})
                self._send_to_zabbix(metrics)
                log.debug(
                    'Dump thread going to sleep for %s seconds',
                    self.dump_interval)
                time.sleep(self.dump_interval)
            except Exception:
                log.error(
                    'Uncaught exception, preventing thread from crashing.',
                    exc_info=True)

    def _send_to_zabbix(self, metrics):
        if not (self.zabbix_server and self.zabbix_nodename):
            log.error('zabbix server or nodename not defined, skipping'
                      ' sending metrics')
            return
        # Work around bug in zbxsend, they keep the fraction which zabbix
        # then rejects.
        now = int(time.time())
        metrics = [zbxsend.Metric(self.zabbix_nodename, key, value, now)
                   for key, value in metrics.items()]
        log.debug(metrics)

        # Try each server in the list if there is more than one.
        sent = False
        for server in self.zabbix_server:
            log.debug('Trying to send metrics to: %s', server)
            if zbxsend.send_to_zabbix(metrics, server):
                log.debug('Sent metrics to: %s', server)
                sent = True
                break
            else:
                log.debug('Failed to send metrics to zabbix server: %s',
                          server)
        if not sent:
            log.error('Failed to send metrics to zabbix servers: %s',
                      self.zabbix_server)

    def check_queue_lengths(self):
        while not self.should_stop:
            try:
                lengths = collections.Counter()

                with self.app.connection() as connection:
                    pipe = connection.channel().client.pipeline(
                        transaction=False)
                    for queue in self.app.conf['task_queues']:
                        if not hasattr(stats_queue, queue.name):
                            setattr(type(stats_queue), queue.name,
                                    scales.Stat(queue.name))
                        # Not claimed by any worker yet
                        pipe.llen(queue.name)
                    # Claimed by worker but not acked/processed yet
                    pipe.hvals('unacked')

                    result = pipe.execute()

                unacked = result.pop()
                for task in unacked:
                    task = json.loads(task.decode('utf-8'))
                    lengths[task[-1]] += 1
                unacked = [[-1] for v in unacked]
                unacked = len([x for x in unacked])

                for llen, queue in zip(result, self.app.conf['task_queues']):
                    lengths[queue.name] += llen

                for queue, length in lengths.items():
                    setattr(stats_queue, queue, length)

                time.sleep(self.queuelength_interval)
            except Exception:
                log.error(
                    'Uncaught exception, preventing thread from crashing.',
                    exc_info=True)

    def run(self, **kw):
        receiver = Receiver(self.app)

        try_interval = 1
        while not self.should_stop:
            try:
                try_interval *= 2
                receiver()
                try_interval = 1
            except (KeyboardInterrupt, SystemExit):
                log.info('Exiting')
                receiver.should_stop = True
                self.should_stop = True
                thread.interrupt_main()
                break
            except Exception as e:
                log.error(
                    'Failed to capture events: "%s", '
                    'trying again in %s seconds.',
                    e, try_interval, exc_info=True)
                time.sleep(try_interval)

    def prepare_args(self, *args, **kw):
        options, args = super(Command, self).prepare_args(*args, **kw)
        self.app.log.setup(
            logging.DEBUG if options.get('verbose') else logging.INFO)

        self._configure_zabbix(options)
        self.dump_interval = options.pop('dump_interval')
        threading.Thread(target=self.dump_stats).start()

        self.queuelength_interval = options.pop('queuelength_interval')
        if self.queuelength_interval:
            threading.Thread(target=self.check_queue_lengths).start()

        return options, args

    def _configure_zabbix(self, options):
        agent_config = options.get('zabbix_agent_config')
        self.zabbix_server = options.get('zabbix_server')
        self.zabbix_nodename = options.get('zabbix_nodename')

        if agent_config and (not self.zabbix_server or
                             not self.zabbix_nodename):
            log.debug('Using zabbix agent config: %s', agent_config)
            text = open(agent_config).read()
            text = unicode('[general]\n' + text, "utf-8")
            config = ConfigParser()
            config.readfp(StringIO(text))
            if not self.zabbix_server and config.has_option('general',
                                                            'ServerActive'):
                # First try to get ServerActive if defined
                self.zabbix_server = config.get('general', 'ServerActive')
            if not self.zabbix_server and config.has_option('general',
                                                            'Server'):
                # Fall back to Server
                self.zabbix_server = config.get('general', 'Server')
            if not self.zabbix_nodename and config.has_option('general',
                                                              'Hostname'):
                self.zabbix_nodename = config.get('general', 'Hostname')

        # The server option in the agent config file can be
        # a comma separated list, turn it into an array to be used later.
        self.zabbix_server = self.zabbix_server.split(',')
        log.debug('Using zabbix server name/ip list: %s', self.zabbix_server)
        log.debug('Using zabbix nodename: %s', self.zabbix_nodename)

    def add_arguments(self, parser):
        parser.add_argument(
            '--verbose', help='Enable debug logging', action='store_true')

        parser.add_argument('--zabbix-server', help='Zabbix server name')
        parser.add_argument(
            '--zabbix-nodename', help='Report to zabbix as this hostname')
        parser.add_argument(
            '--zabbix-agent-config', help='Path to zabbix_agentd.conf, '
            'to read zabbix server+port and hostname from.')

        parser.add_argument(
            '--dump-interval',
            help='Send metrics to zabbix every x seconds',
            type=int, default=60)

        parser.add_argument(
            '--queuelength-interval',
            help='Check queue lengths every x seconds (0=disabled)',
            type=int, default=0)
