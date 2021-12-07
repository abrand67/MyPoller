#!/usr/bin/env python
"""
Copyright 2019 Allan Brand

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""
__author__ = 'Allan Brand'
__copyright__ = 'Copyright 2019'
__credits__ = ['Allan Brand']
__license__ = 'Apache v2.0'
__version__ = '0.1.0'
__maintainer__ = 'Allan Brand'
__email__ = 'allan.brand@gmail.com'
__status__ = 'Work In Progress'

import time, os, signal
import threading
from queue import Queue

nThreads = 8
eQueue = Queue()
tLock = threading.Lock()
signal.signal(signal.SIGPIPE, signal.SIG_DFL)
signal.signal(signal.SIGINT, signal.SIG_DFL)
