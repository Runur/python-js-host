import json
import atexit
import time
from .service_host import ServiceHost
from .conf import settings, Verbosity
from .exceptions import UnexpectedResponse


class ManagedServiceHost(ServiceHost):
    manager = None

    def __init__(self, manager):
        self.manager = manager

        # Reuse the manager's config to avoid the overhead of reading the file
        # again. Once `start` is called, the config will be updated with the actual
        # config called by the host.
        self.config = self.manager.get_config()

        super(ManagedServiceHost, self).__init__(
            path_to_node=manager.path_to_node,
            path_to_node_modules=manager.path_to_node_modules,
            config_file=manager.config_file
        )

    def start(self):
        """
        Connect to the manager and request a host using the host's config file.

        Managed hosts run on ports allocated by the OS and the manager is used
        to keep track of the ports used by each host. When we call host.start(),
        we ask the manager to start the host as a subprocess, only if it is not
        already running. Once the host is running, the manager returns the config
        used by the subprocess so that our host knows where to send requests
        """
        res = self.manager.send_request('start', params={'config': self.config_file}, post=True)

        if res.status_code != 200:
            raise UnexpectedResponse(
                'Attempted to start a {cls_name}: {res} - {res_text}'.format(
                    cls_name=type(self).__name__,
                    res=res,
                    res_text=res.text
                )
            )

        host_json = res.json()

        self.config = json.loads(host_json['output'])

        if host_json['started'] and settings.VERBOSITY >= Verbosity.PROCESS_START:
            print('Started {}'.format(self.get_name()))

        # When the python process exits, we ask the manager to stop the
        # host after a timeout. If the python process is merely restarting,
        # the timeout will be cancelled when the next connection is opened.
        # If the python process is shutting down for good, this enables some
        # assurance that the host's process will inevitably stop.
        atexit.register(
            self.stop,
            timeout=settings.ON_EXIT_MANAGED_HOSTS_STOP_TIMEOUT,
        )

    def stop(self, timeout=None):
        """
        Stops a managed host.

        `timeout` specifies the number of milliseconds that the host will be
        stopped in. If `timeout` is provided, the method will complete while the
        host is still running
        """

        if not self.is_running():
            return

        params = {'config': self.config_file}

        if timeout:
            params['timeout'] = timeout

        res = self.manager.send_request('stop', params=params, post=True)

        if res.status_code != 200:
            raise UnexpectedResponse(
                'Attempted to stop {name}. Response: {res_code}: {res_text}'.format(
                    name=self.get_name(),
                    res_code=res.status_code,
                    res_text=res.text,
                )
            )

        if not timeout:
            # The manager will stop the host after a few milliseconds, so we need to
            # ensure that the state of the system is as expected
            time.sleep(0.05)

        if settings.VERBOSITY >= Verbosity.PROCESS_STOP:
            if timeout:
                print(
                    '{name} will stop in {seconds} seconds'.format(
                        name=self.get_name(),
                        seconds=timeout / 1000.0,
                    )
                )
            else:
                print('Stopped {}'.format(self.get_name()))

    def restart(self):
        self.stop()
        self.start()
        self.connect()