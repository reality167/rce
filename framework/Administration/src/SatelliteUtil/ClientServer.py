#!/usr/bin/env python
# -*- coding: utf-8 -*-

# twisted specific imports
from twisted.python import log
from twisted.internet.task import LoopingCall
from autobahn.websocket import WebSocketServerFactory, WebSocketServerProtocol

# Python specific imports
from datetime import datetime, timedelta
import json
import uuid

try:
    from cStringIO import StringIO, InputType, OutputType
    
    def _checkIsStringIO(obj):
        return isinstance(obj, (InputType, OutputType))
except ImportError:
    from StringIO import StringIO
    
    def _checkIsStringIO(obj):
        return isinstance(obj, StringIO)

# Custom imports
import settings
from Exceptions import InvalidRequest
from Robot import Robot
import ClientMsgTypes

class WebSocketCloudEngineProtocol(WebSocketServerProtocol):
    """ Protocol which is used for the connections from the robots to the reCloudEngine.
    """
    def __init__(self, commManager, satelliteManager):
        """ Initialize the Protocol.
        """
        self._commManager = commManager
        self._satelliteManager = satelliteManager
        self._robot = None
        self._incompleteMsgs = []   # List of tuples (incompleteMsg, incompleteURIList, arrivalTime)
        
        # Setup repeated calling of the clean up method
        LoopingCall(self._cleanUp).start(settings.MSG_QUQUE_TIMEOUT/4)
    
    def _recursiveURISearch(self, multidict):
        """ Internally used method to find binary data in incoming messages.
        """
        valueList = []
        
        for k,v in multidict.iteritems():
            if isinstance(v, dict):
                valueList += self._recursiveURISearch(v)
            elif k[-1] == '*':
                valueList.append((v, multidict, k))
        
        return valueList
    
    def _strMsgHandle(self, msg):
        """ Internally used method to handle incoming string messages.
        """
        data = msg['data']
        
        if msg['type'] == ClientMsgTypes.CREATE_CONTAINER:
            if not self._robot:
                self._robot = Robot(self._commManager, self._satelliteManager, self, msg['orig'])
            self._robot.createContainer(data['containerTag'])
        
        elif msg['type'] == ClientMsgTypes.DESTROY_CONTAINER:
            self._robot.destroyContainer(data['containerTag'])
        
        elif msg['type'] == ClientMsgTypes.CHANGE_COMPONENT:
            if 'addNodes' in data:
                for node in data['addNodes']:
                    self._robot.addNode(msg['dest'], node['nodeTag'], node['pkg'], node['exe'], node['namespace'])
                
            if 'removeNodes' in data:
                for nodeTag in data['removeNodes']:
                    self._robot.removeNode(msg['dest'], nodeTag)
                
            if 'addInterfaces' in data:
                for interfaceConfig in data['addInterfaces']:
                    self._robot.addInterface( msg['dest'],
                                              interfaceConfig['name'],  # <- Interface Tag for simplicity equal to inteface name!
                                              interfaceConfig['name'],
                                              interfaceConfig['interfaceType'],
                                              interfaceConfig['className'] )

            if 'removeInterfaces' in data:
                for interfaceTag in data['removeInterfaces']:
                    self._robot.removeInterface(msg['dest'], interfaceTag)

            if 'setParam' in data:
                for param in  data['setParam']:
                    self._robot.addParameter(msg['dest'], param['paramName'] , param['paramValue'],  param['paramType'])
                    
            if 'deleteParam' in data:
                for paramName in data['deleteParam']:
                    self._robot.removeParameter(msg['dest'], paramName)
        
        elif msg['type'] == ClientMsgTypes.INTERFACE_STATE:
            for interfaceTag, activate in data.iteritems():
                if activate:
                    self._robot.activateInterface(msg['dest'], interfaceTag)
                else:
                    self._robot.deactivateInterface(msg['dest'], interfaceTag)
        
        elif msg['type'] == ClientMsgTypes.MESSAGE:
            uriList = self._recursiveURISearch(data['msg'])
            if uriList:
                self._incompleteMsgs.append((msg, uriList, datetime.now()))
            else:
                self._robot.sendROSMsgToContainer(msg['dest'], data)
        else:
            raise InvalidRequest('This type is not supported')
    
    def _binaryMsgHandle(self, msg):
        """ Internally used method to handle incoming binary messages.
        """
        uri = msg[:32]
        binaryData = StringIO().write(msg[33:])
        
        # Find and replace URI with data
        for incompleteMsg in self._incompleteMsgs:
            msg, incompleteURIList, _ = incompleteMsg
            
            for incompleteUri in incompleteURIList:
                missingUri, msgDict, key = incompleteUri
                
                if uri == missingUri:
                    del msgDict[key]
                    msgDict[key[:-1]] = binaryData
                    incompleteURIList.remove(incompleteUri)
                    
                    if not incompleteURIList:
                        self._robot.sendROSMsgToContainer(msg['dest'], msg['data'])
                        self._incompleteMsgs.remove(incompleteMsg)
                    
                    return
    
    def onMessage(self, msg, binary):    
        """ Method is called by the Autobahn engine when a message has been received
            from the client.
        """
        log.msg('WebSocket: Received new message from robot.')
        
        try:
            if binary:
                self._binaryMsgHandle(msg)
            else:
                self._strMsgHandle(json.loads(msg))
        except Exception:   # TODO: Refine Error handling
            #import sys, traceback
            #etype, value, _ = sys.exc_info()
            #WebSocketServerProtocol.sendMessage(self, '\n'.join(traceback.format_exception_only(etype, value)))
            
            # Full debug message
            import traceback
            WebSocketServerProtocol.sendMessage(self, traceback.format_exc())
    
    def _recursiveBinarySearch(self, multidict):
        """ Internally used method to find binary data in outgoing messages.
        """
        uriBinary = []
        keys = []
        
        for k,v in multidict.iteritems():
            if isinstance(v, dict):
                uriBinaryPart, multidictPart = self._recursiveBinarySearch(v)
                uriBinary += uriBinaryPart
                multidict[k] = multidictPart 
            elif _checkIsStringIO(v):
                keys.append(k)
        
        for k in keys:
            tmpURI = uuid.uuid4().hex
            uriBinary.append((tmpURI, v))
            del multidict[k]
            multidict['{0}*'.format(k)] = tmpURI
        
        return uriBinary, multidict
    
    def sendMessage(self, msg):
        """ This method is called by the Robot instance to send a message to the robot.
            
            @param msg:     Message which should be sent
        """
        URIBinary, msgURI = self._recursiveBinarySearch(msg)
        
        WebSocketServerProtocol.sendMessage(self, json.dumps(msgURI))
        
        for binData in URIBinary:
            WebSocketServerProtocol.sendMessage(self, binData[0] + binData[1].getvalue(), binary=True)
            
    def connectionLost(self, reason):
        """ Method is called by the twisted engine when the connection has been lost.
        """
        self._robot = None
    
    def _cleanUp(self):
        """ Internally used method to remove old incomplete messages.
        """
        limit = datetime.now() - timedelta(seconds=settings.MSG_QUQUE_TIMEOUT)
        
        for i in xrange(len(self._incompleteMsgs)):
            if self._incompleteMsgs[i][2] > limit:
                if i:
                    self._incompleteMsgs = self._incompleteMsgs[i:]
                    log.msg('{0} Incomplete message(s) have been dropped from cache.'.format(i))
                
                break
    
class WebSocketCloudEngineFactory(WebSocketServerFactory):
    """ Factory which is used for the connections from the robots to the reCloudEngine.
    """
    def __init__(self, commManager, satelliteManager, url):
        """ Initialize the Factory.
        """
        WebSocketServerFactory.__init__(self, url)
        
        self._commManager = commManager
        self._satelliteManager = satelliteManager
    
    def buildProtocol(self, addr):
        """ Method is called by the twisted reactor when a new connection attempt is made.
        """
        p = WebSocketCloudEngineProtocol(self._commManager, self._satelliteManager)
        p.factory = self
        return p
