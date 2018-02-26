=============
celery_zabbix
=============

Sends task execution metrics to Zabbix: how many tasks were started and have
completed successfully or with failure, and how many tasks are still in the
queues (supported only for broker redis).

Inspired by https://gitlab.com/kalibrr/celery-prometheus


Usage
=====

Run ``bin/celery zabbix --zabbix-nodename myhost.example.com --zabbix-server zabbix.example.com``.

Alternatively you can pass ``--zabix-agent-config=/etc/zabbix/zabbix_agentd.conf``, then the values for server+nodename will be read from there.

The following items will be sent every 60 seconds (pass ``--dump-interval=x`` to configure):

* celery.task.started
* celery.task.succeeded
* celery.task.failed
* celery.task.retried

These are counted from the time the monitoring process started,
so you'll probably want to process them as delta on the Zabbix server.

* celery.task.queuetime (only if ``task_send_sent_event`` is enabled)
* celery.task.runtime

These are the median values.

If you pass ``--queuelength-interval=x`` then every x seconds the queue lengths will be checked (only works with redis), and the following items will also be sent:

* celery.queue.NAME.length

These are gauge values, i.e. they contain the length as it was retrieved each
time, so they can go up and down.


Run tests
=========

Using `tox`_ and `py.test`_. Maybe install ``tox`` (e.g. via ``pip install tox``)
and then simply run ``tox``.

.. _`tox`: http://tox.readthedocs.io/
.. _`py.test`: http://pytest.org/
