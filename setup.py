from setuptools import setup, find_packages


setup(
    name='celery_zabbix',
    version='1.0.0',
    author='Zeit Online',
    author_email='zon-backend@zeit.de',
    url='https://github.com/zeitonline/celery_zabbix',
    description="Sends task execution metrics to Zabbix",
    long_description='\n\n'.join(
        open(x).read() for x in ['README.rst', 'CHANGES.txt']),
    packages=find_packages('src'),
    package_dir={'': 'src'},
    include_package_data=True,
    zip_safe=False,
    license='BSD',
    install_requires=[
        'celery',
        'scales',
        'setuptools',
        'zbxsend',
    ],
    extras_require={'test': [
        'mock',
        'pytest',
    ]},
    entry_points={
        'celery.commands': [
            'zabbix = celery_zabbix.receiver:Command',
        ]
    }
)
