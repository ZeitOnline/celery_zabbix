=============
celery_zabbix
=============

Sends task execution metrics to Zabbix: how many tasks were started and have
completed successfully or with failure, and how many tasks are still in the
queues (supported only for broker redis).

Inspired by `https://gitlab.com/kalibrr/celery-prometheus`_.


Usage
=====

Run ``bin/celery zabbix --nodename myhost.example.com --zabbix-server zabbix.example.com``

The following items will be sent:

* celery.task.started
* celery.task.succeeded
* celery.task.failed
* celery.task.retried
* celery.task.queuetime (only if ``task_send_sent_event`` is enabled)
* celery.task.runtime
* celery.queue.NAME.length


Run tests
=========

Using `tox`_ and `py.test`_. Maybe install ``tox`` (e.g. via ``pip install tox``)
and then simply run ``tox``.

.. _`tox`: http://tox.readthedocs.io/
.. _`py.test`: http://pytest.org/
