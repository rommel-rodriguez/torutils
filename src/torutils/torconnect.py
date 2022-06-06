import requests
from requests.exceptions import ConnectionError
import io
import shutil
import sys
from . import config  # Necessary when in packages
import time
import random
import stem.process
from stem.util import term
from stem import Signal
from stem.control import Controller
import threading

## Requester config
## TODO: Add support for session and sessionless requester in TorConnection


def log_msg(msg):
    """ Log a message including a time stamp
    """
    from datetime import datetime as dd
    ts = '[ {} ] '.format(dd.now())
    print(ts + msg)
## END Requester config

def get_public_ip(requester):
    """
    @param requester    Any kind of object that can make HTTP/HTTPS requests
    @return current visible IPv4 address
    """
    try:
        # rsp=requester.get('http://httpbin.org/ip')
        rsp=requester.get('http://ip.jsontest.com')

    except ConnectionError as e:
        log_msg(str(e))
        tor_process.kill()
        sys.exit(1)
    # return rsp.json()['origin']
    return rsp.json()['ip']

# TODO: Consider just including this function inside start_tor method
def print_bootstrap_lines(line):
  if "Bootstrapped " in line:
    print(term.format(line, term.Color.BLUE))

    

class TorConnection:
    def __init__(self, 
            proxy_host='localhost', 
            proxy_port = '9050' , 
            control_port = '9051'):
        self.__dict__['proxy_host'] = proxy_host
        self.__dict__['proxy_port'] = proxy_port
        self.__dict__['control_port'] = control_port
        self.tor = None
        self.controller = None
        ## Requester Settings
        ## TODO: ERROR this will fail move it elsewhere
        self.headers = {'user-agent':config.USER_AGENT}
        socks_proxy = 'socks5h://' + self.proxy_host + ':' + self.proxy_port
        self.__proxies = {'http': socks_proxy,
                'https': socks_proxy} 

        self.__dict__['requester'] = None
        ### NOTE: This will mess up the requests get function,
        ### possibly messing up many parts of this script, throughly test it
        ## requests.get = get_decorator(requests.get, self.headers, self.__proxies)
        ## self.__dict__['nosess_requester'] = requests
        self.__dict__['nosess_requester'] = requests

    def get(self, url, **kwargs):
        ''' Requests Get Method with headers and Tor Proxies configured '''
        #print(f'inside no_sess_get, args:{tuple(args)}')
        return requests.get(url, 
                headers=self.headers, 
                proxies=self.__proxies, 
                **kwargs
                )
    def post(self, url, **kwargs):
        '''  Requests Post Method with headers and Tor Proxies configured '''
        return requests.get(url, 
                headers=self.headers, 
                proxies=self.__proxies, 
                **kwargs ### e.g. the data and json keyworded arguments
                )


    @property
    def proxy_host(self):
        ''' Tor Server Host '''
        return self.__dict__['proxy_host']


    @property
    def proxy_port(self):
        ''' Tor Server Port'''
        return self.__dict__['proxy_port']
    
    @proxy_port.setter
    def proxy_port(self, value):
        print(f'Attempting to change Tor\'s Port from {self.proxy_port} to {value}')
        if not isinstance(value, str): 
            raise ValueError(f'value:{value} must be a string')

        self.__dict__['proxy_port'] = value
        ### TODO: Repeated code, fix it
        socks_proxy = 'socks5h://' + self.proxy_host + ':' + self.proxy_port
        self.__proxies = {'http': socks_proxy,
                'https': socks_proxy} 
        log_msg('Tor Server configuration changed restarting Tor ...')
        self.stop_tor()
        self.start_tor()

        return self.__dict__['proxy_host']

    @property
    def control_port(self):
        ''' Tor Server Control Port'''
        return self.__dict__['control_port']

    def start_tor(self):
        # TODO: Add logic to handle Errors/Exceptions
        # TODO: Consider adding ExitNodes to config and to __init__
        data_directory = '/tmp/tordata' + str(random.randint(1,2**64))
        self.tor = stem.process.launch_tor_with_config(
            config = {
                'SocksPort': str(self.proxy_port),
                'ControlPort': self.control_port,
                #    'ExitNodes': '{us}, {ca}, {ru}',
                'DataDirectory': data_directory,
                'ExitNodes': '{us},{ca},{au},{fr},{de},{gr},{gl}'
            },
            init_msg_handler = print_bootstrap_lines,
        )
        self.__data_directory = data_directory ## Delete this folder at object's death
        self.__set_controller()
        # NOTE: IF everything checks up set the requester object
        self.__create_requester()
        return

    def __create_requester(self):
        ''' '''
        # TODO: what to do with USER_AGENT?
        _s = requests.Session()
        _s.headers.update(self.headers)
        _s.proxies.update(self.__proxies)
        self.__dict__['requester'] = _s


    def __set_controller(self):
        self.controller = Controller.from_port( port = int(self.control_port) )
        self.controller.authenticate()

    def stop_tor(self):
        ''' Stops the instanc's tor process '''
        # Sesssion needs to be close or the new session will conflict with the old one
        self.__dict__['requester'].close() 
        self.tor.kill()
        self.tor.wait()
    
    def get_new_identity(self):
        ''' Restarts the Tor Process in order to get a new circuit and new Exit Node '''
        return self.__brute_reset_tor()

    def __brute_reset_tor(self):
        ## Consider storing the current_ip in a cache inside the object
        current_ip = self.get_identity()
        self.stop_tor()
        # time.sleep(2)
        # self.tor = None
        ## TODO: Do I need some time.sleep() here?
        ## TODO: Seems like Unittest fails here
        self.start_tor()
        while True:
            new_ip = self.get_identity()
            if new_ip and current_ip != new_ip:
                print("==> New IP obtained: {}".format(new_ip))
                break
            print("No change in IP: {}".format(new_ip))
        return new_ip 

    def __dirty_mark_circuit(self):
        current_ip = self.get_identity()
        while True:
            ## TODO: Find out why this does NOT work
            ## ANSWER: 
            ## https://stackoverflow.com/questions/45092345/stem-is-not-generating-\
            ##         new-ip-address-in-python
            # This instruction was never meant to change the Exit Node but just to 
            # mark the current circuit as dirty
            self.controller.signal(Signal.NEWNYM)
            time.sleep(self.controller.get_newnym_wait())
            new_ip = self.get_identity() 
            if new_ip and current_ip != new_ip:
                log_msg("==> New IP obtained: {}".format(new_ip))
                break
            log_msg("No change in IP: {}".format(new_ip))
        log_msg("No IP change performed")
        return new_ip 
    ## TODO: Add functionality for the Tor Process to be killed when this object
    ## is deleted


    @property
    def requester(self):
        ''' The requester attribute '''
        ## TODO: Add logic to this, so it only works if self.tor is already set
        if not self.tor: print('[WARNING] Be aware that the proxy is not ready yet')
        return self.__dict__['requester']

    def get_identity(self):
        ''' '''
        return self.requester.get('http://httpbin.org/ip').json()['origin']

    def __repr__(self):
        _this_class = type(self).__name__
        return '{}(\'{}\',\'{}\',\'{}\')'.format(_this_class, 
                                                self.proxy_host,
                                                self.proxy_port,
                                                self.control_port
                                                )
                

    def __str__(self):
        return 'Tor Connection Listening on: {:5s}\nControl port on: {:5s}'.format(
                    self.proxy_port, self.control_port
                )

    def __del__(self):
        self.stop_tor()
        ## TODO: Maybe add support for OSError or something
        if self.__data_directory: 
            try:
                shutil.rmtree(self.__data_directory)
            except OSError as e:
                print("Error: %s : %s" % (self.__data_directory, e.strerror))
        
        
### TODO:Implement a class with a method to easy spawn tor threads using a Queue or a Queue-like object

class TorThreadGenerator:

    @staticmethod
    def _queue_thrwrapper(f, que, fargs,fwargs):
        while not que.empty():
            item = que.get()
            if not isinstance(fargs[0], TorConnection): 
                print(f'Typeof(fargs[0]): {type(fargs[0]).__name__}')
                raise ValueError('This should be a TorConnection Object!!!')
            if fargs[1] is not None:
                raise ValueError('The Queue Item placeholder should initially be None !!!')
            else:
                fargs[1] = item

            f(*fargs,**fkwargs)

    def start_threads(self, f, que, fargs=[],fkwargs={},
                        proxy_port='9250', threads=1, port_step=100):
        ''' Given a function f starts "threads" number of threads until 
            a Queue is empty or condition is met
        @param  f    a Tor aware or Tor Requester aware function, assumes the first argument
                     is a torcon set initially to None, and second is the item to download,
                     the item can be of any type but initially it should be null
        @param  que   Queue object on which's items f will perform operations on 
        @param  fargs a list of positional arguments for the function
        @param  fkwargs a dict of keyworded arguments for the function 
        @param  proxy_port   str Starting Tor Server Port
        @param  threads int Number of threads to spawn
        @param  port_step   Amount of automatic increment in ports
        '''
        ## TODO: This and _queue_thwrapper are only pseudo code for now,
        ## I might even get syntax error, the thing is, what to do with the function's other
        ## arguments the one I will NOT know about before hand, order *args and **kwargs?
        ## Take into accout that get must pass its parameters through the tuple at Thread
        ## creation, wrapping all the arguments inside a dict or tuple and assuming which
        ## is the torcon and the q(queue) is too restrictive
        control_port = str(int(proxy_port)+1)
        for i in range(threads):
            torcon = TorConnection(proxy_port=proxy_port, control_port=control_port)
            torcon.start_tor() ## Start the Tor Server for the thread
            ## NOTE: We are assuming that the first argument of the function (torcon)
            ## is None by default
            if fargs[0] is None:
                fargs[0] = torcon
            else:
                raise ValueError('fargs first value represents torcon which should be set null by the user')
            th = threading.Thread(target=TorThreadGenerator._queue_thrwrapper,
                                    args= (f, que, fargs, fwargs)
                                 )
            th.start()
            proxy_port = str(int(proxy_port)+port_step)
            control_port = str(int(control_port)+port_step)


    @staticmethod
    def _queue_thrwrapper_multi(f, fargs,fkwargs):
        ''' Iterations and Item retrieval are offloaded to the function f '''
        if not isinstance(fargs[0], TorConnection): 
            print(f'Typeof(fargs[0]): {type(fargs[0]).__name__}')
            raise ValueError('This should be a TorConnection Object!!!')
        fargs[0].start_tor()
        ### TODO: I think my new implementation does not need me to 
        ### Restrict the second argument to a Queue, if this is true
        ### remove any such restrictive code
        if fargs[1] is None:
            raise ValueError('The Queue Object is missing !!!')

        f(*fargs,**fkwargs)

    @staticmethod
    def start_threads_multi(f, fargs=[],fkwargs={},
                        proxy_port='9250', threads=1, port_step=100):
        ''' Given a function f starts "threads" number of threads until 
            a Queue is empty or condition is met
        @param  f    a Tor aware or Tor Requester aware function, assumes the first argument
                     is a torcon set initially to None, and second is the to be worked on
        @param  fargs a list of positional arguments for the function
        @param  fkwargs a dict of keyworded arguments for the function 
        @param  proxy_port   str Starting Tor Server Port
        @param  threads int Number of threads to spawn
        @param  port_step   Amount of automatic increment in ports
        '''
        ## TODO: Add functionality to wait until all threads are done, for that
        ## I need to create a thread list, or use ThreadPoolExecutor
        control_port = str(int(proxy_port)+1)
        thlist = [] # List of Threads
        for i in range(threads):
            torcon = TorConnection(proxy_port=proxy_port, control_port=control_port)
            ## NOTE: Should I run start_tor inside the Thread? or Here
            # torcon.start_tor() ## Start the Tor Server for the thread
            ## NOTE: We are assuming that the first argument of the function (torcon)
            ## is None by default
            if not fargs or fargs[0] is None:
                fargs[0] = torcon
            else:
                raise ValueError('fargs first value represents torcon which should be set null by the user')
            th = threading.Thread(target=TorThreadGenerator._queue_thrwrapper_multi,
                                    args= (f, fargs, fkwargs)
                                 )
            thlist.append(th)
            th.start()
            ## Prepare for next iteration
            proxy_port = str(int(proxy_port)+port_step)
            control_port = str(int(control_port)+port_step)
            #fargs[0] = None ## Causing problems, eliminatiing my torcon, is this possible
            fargs = [None, fargs[1]]
        
        for thr in thlist: thr.join()

if __name__ == '__main__':
    torrc = { 'proxy_host' : 'localhost', 'proxy_port' : '9050', 'control_port' : '9051'}
    torcon = TorConnection(**torrc)
    torcon.start_tor()
    log_msg('Current IP: %s' % torcon.get_identity())
    #print(torcon.requester.get('https://google.com').text)
    torcon.get_new_identity()
    log_msg('Current IP: %s' % torcon.get_identity())
    print(repr(torcon))
