from functools import wraps
from greplin import scales
import celery.bin.base
import logging
import thread
import threading
import time


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
        if task is not None:
            stats.runtime = task.runtime

    @task_handler
    def on_task_failed(self, event, task):
        log.debug('Failed %s', task)
        stats.failed += 1
        if task is not None:
            stats.runtime = task.runtime

    @task_handler
    def on_task_retried(self, event, task):
        log.debug('Retried %s', task)
        stats.retried += 1
        if task is not None:
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


class Command(celery.bin.base.Command):

    should_stop = False

    def dump_stats(self):
        while not self.should_stop:
            data = scales.getStats()
            log.debug(data)
            log.debug(
                'Dump thread going to sleep for %s seconds',
                self.dump_interval)
            time.sleep(self.dump_interval)

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
        self.dump_interval = options.pop('dump_interval')
        threading.Thread(target=self.dump_stats).start()
        return options, args

    def add_arguments(self, parser):
        parser.add_argument(
            '--dump-interval',
            help='Send metrics to zabbix every x seconds', type=int, default=1)
        parser.add_argument(
            '--verbose', help='Enable debug logging', action='store_true')
