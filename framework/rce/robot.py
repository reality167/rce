#!/usr/bin/env python
# -*- coding: utf-8 -*-
#     
#     robot.py
#     
#     This file is part of the RoboEarth Cloud Engine framework.
#     
#     This file was originally created for RoboEearth
#     http://www.roboearth.org/
#     
#     The research leading to these results has received funding from
#     the European Union Seventh Framework Programme FP7/2007-2013 under
#     grant agreement no248942 RoboEarth.
#     
#     Copyright 2013 RoboEarth
#     
#     Licensed under the Apache License, Version 2.0 (the "License");
#     you may not use this file except in compliance with the License.
#     You may obtain a copy of the License at
#     
#     http://www.apache.org/licenses/LICENSE-2.0
#     
#     Unless required by applicable law or agreed to in writing, software
#     distributed under the License is distributed on an "AS IS" BASIS,
#     WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#     See the License for the specific language governing permissions and
#     limitations under the License.
#     
#     \author/s: Dominique Hunziker 
#     
#     

# Python specific imports
import sys
from uuid import UUID

# zope specific imports
from zope.interface import implements

# twisted specific imports
from twisted.python import log
from twisted.python.failure import Failure
from twisted.internet.defer import fail, maybeDeferred
from twisted.cred.error import UnauthorizedLogin
from twisted.cred.checkers import ICredentialsChecker
from twisted.cred.portal import IRealm, Portal
from twisted.spread.pb import PBClientFactory, \
    DeadReferenceError, PBConnectionLost

# Autobahn specific imports
from autobahn.websocket import listenWS

# Custom imports
from rce.error import InternalError, DeadConnection
from rce.client.interfaces import IRobot, IRobotCredentials
from rce.client.protocol import CloudEngineWebSocketFactory
from rce.monitor.converter import PublisherConverter, SubscriberConverter, \
    ServiceClientConverter, ServiceProviderConverter, \
    PublisherForwarder, SubscriberForwarder, \
    ServiceClientForwarder, ServiceProviderForwarder
from rce.slave.endpoint import Endpoint
from rce.slave.namespace import Namespace


class Robot(Namespace):
    """ Representation of a namespace in the robot process, which is part of
        the cloud engine internal communication.
    """
    implements(IRobot)
    
    _MAP = [ServiceClientConverter, PublisherConverter,
            SubscriberConverter, ServiceProviderConverter,
            ServiceClientForwarder, PublisherForwarder,
            SubscriberForwarder, ServiceProviderForwarder]
    
    def __init__(self, client, user):
        """ Initialize the Robot.
            
            @param client:      Robot Client which is responsible for
                                monitoring the robots in this process.
            @type  client:      rce.robot.RobotClient
            
            @param user:        Remote reference to the User instance who owns
                                this robot.
            @type  user:        twisted.spread.pb.RemoteReference
        """
        self._client = client
        client.registerRobot(self)
        
        self._user = user
        self._connection = None
        
        # The following replaces the call to Namespace.__init__()
        self._interfaces = {}
    
    def _reportError(self, failure):
        self._connection.sendErrorMessage(failure.getTraceback())
    
    def createContainer(self, tag):
        """ Create a new Container object.
            
            @param tag:         Tag which is used to identify the container
                                in subsequent requests.
            @type  tag:         str
        """
        try:
            d = self._user.callRemote('createContainer', tag)
        except (DeadReferenceError, PBConnectionLost):
            raise DeadConnection()
        
        d.addErrback(self._reportError)
    
    def destroyContainer(self, tag):
        """ Destroy a Container object.
            
            @param tag:         Tag which is used to identify the container
                                which should be destroyed.
            @type  tag:         str
        """
        try:
            d = self._user.callRemote('destroyContainer', tag)
        except (DeadReferenceError, PBConnectionLost):
            raise DeadConnection()
        
        d.addErrback(self._reportError)
    
    def addNode(self, cTag, nTag, pkg, exe, args='', name='', namespace=''):
        """ Add a node to a container / ROS environment.
            
            @param cTag:        Tag which is used to identify the container /
                                ROS environment to which the node should be
                                added.
            @type  cTag:        str
            
            @param nTag:        Tag which is used to identify the node in
                                subsequent requests.
            @type  nTag:        str

            @param pkg:         Name of ROS package where the node can be
                                found.
            @type  pkg:         str

            @param exe:         Name of executable (node) which should be
                                launched.
            @type  exe:         str
            
            @param args:        Additional arguments which should be used for
                                the launch. Can contain the directives
                                $(find PKG) and/or $(env VAR). Other special
                                characters such as '$' or ';' are not allowed.
            @type  args:        str
            
            @param name:        Name of the node under which the node should be
                                launched.
            @type  name:        str
            
            @param namespace:   Namespace in which the node should be started
                                in the environment.
            @type  namespace:   str
        """
        try:
            d = self._user.callRemote('addNode', cTag, nTag, pkg, exe, args,
                                      name, namespace)
        except (DeadReferenceError, PBConnectionLost):
            raise DeadConnection()
        
        d.addErrback(self._reportError)
    
    def removeNode(self, cTag, nTag):
        """ Remove a node from a container / ROS environment.
            
            @param cTag:        Tag which is used to identify the container /
                                ROS environment from which the node should be
                                removed.
            @type  cTag:        str
            
            @param nTag:        Tag which is used to identify the ROS node
                                which should removed.
            @type  nTag:        str
        """
        try:
            d = self._user.callRemote('removeNode', cTag, nTag)
        except (DeadReferenceError, PBConnectionLost):
            raise DeadConnection()
        
        d.addErrback(self._reportError)
    
    def addInterface(self, eTag, iTag, iType, clsName, addr=''):
        """ Add an interface to an endpoint, i.e. a ROS environment or a 
            Robot object.
            
            @param eTag:        Tag which is used to identify the endpoint to
                                which the interface should be added; either
                                a container tag or robot ID.
            @type  eTag:        str
                            
            @param iTag:        Tag which is used to identify the interface in
                                subsequent requests.
            @type  iTag:        str
            
            @param iType:       Type of the interface. The type consists of a
                                prefix and a suffix.
                                 - Valid prefixes are:
                                     ServiceClient, ServiceProvider,
                                     Publisher, Subscriber
                                 - Valid suffixes are:
                                     Interface, Converter, Forwarder
            @type  iType:       str
            
            @param clsName:     Message type/Service type consisting of the
                                package and the name of the message/service,
                                i.e. 'std_msgs/Int32'.
            @type  clsName:     str
            
            @param addr:        ROS name/address which the interface should
                                use. Only necessary if the suffix of @param
                                iType is 'Interface'.
            @type  addr:        str
        """
        try:
            d = self._user.callRemote('addInterface', eTag, iTag, iType,
                                      clsName, addr)
        except (DeadReferenceError, PBConnectionLost):
            raise DeadConnection()
        
        d.addErrback(self._reportError)
    
    def removeInterface(self, eTag, iTag):
        """ Remove an interface from an endpoint, i.e. a ROS environment or a 
            Robot object.
            
            @param eTag:        Tag which is used to identify the endpoint from
                                which the interface should be removed; either
                                a container tag or robot ID.
            @type  eTag:        str
            
            @param iTag:        Tag which is used to identify the interface
                                which should be removed.
            @type  iTag:        str
        """
        try:
            d = self._user.callRemote('removeInterface', eTag, iTag)
        except (DeadReferenceError, PBConnectionLost):
            raise DeadConnection()
        
        d.addErrback(self._reportError)
    
    def addParameter(self, cTag, name, value):
        """ Add a parameter to a container / ROS environment.
            
            @param cTag:        Tag which is used to identify the container /
                                ROS environment to which the parameter should
                                be added.
            @type  cTag:        str
            
            @param name:        Name of the parameter which should be added.
                                It is also used to identify the parameter in
                                subsequent requests.
            @type  name:        str
            
            @param value:       Value of the parameter which should be added.
                                Top-level string values can contain the
                                directives $(find PKG) and/or $(env VAR).
            @type  value:       str, int, float, bool, list
        """
        try:
            d = self._user.callRemote('addParameter', cTag, name, value)
        except (DeadReferenceError, PBConnectionLost):
            raise DeadConnection()
        
        d.addErrback(self._reportError)
    
    def removeParameter(self, cTag, name):
        """ Remove a parameter from a container / ROS environment.
            
            @param cTag:        Tag which is used to identify the container /
                                ROS environment from which the parameter should
                                be removed.
            @type  cTag:        str
            
            @param name:        Name of the parameter which should be removed.
            @type  name:        str
        """
        try:
            d = self._user.callRemote('removeParameter', cTag, name)
        except (DeadReferenceError, PBConnectionLost):
            raise DeadConnection()
        
        d.addErrback(self._reportError)
    
    def addConnection(self, tagA, tagB):
        """ Create a connection between two interfaces.
            
            @param tagX:        Tag which is used to identify the interface
                                which should be connected. It has to be of the
                                form:
                                    [endpoint tag]/[interface tag]
                                For example:
                                    testRobot/logPublisher
            @type  tagX:        str
        """
        try:
            d = self._user.callRemote('addConnection', tagA, tagB)
        except (DeadReferenceError, PBConnectionLost):
            raise DeadConnection()
        
        d.addErrback(self._reportError)
    
    def removeConnection(self, tagA, tagB):
        """ Destroy a connection between two interfaces.
            
            @param tagX:        Tag which is used to identify the interface
                                which should be disconnected. It has to be of
                                the form:
                                    [endpoint tag]/[interface tag]
                                For example:
                                    testRobot/logPublisher
            @type  tagX:        str
        """
        try:
            d = self._user.callRemote('removeConnection', tagA, tagB)
        except (DeadReferenceError, PBConnectionLost):
            raise DeadConnection()
        
        d.addErrback(self._reportError)
    
    def receivedFromClient(self, iTag, clsName, msgID, msg):
        """ Process a data message which has been received from the robot
            client and send the message to the appropriate interface.
                            
            @param iTag:        Tag which is used to identify the interface to
                                which this message should be sent.
            @type  iTag:        str
            
            @param clsName:     Message type/Service type consisting of the
                                package and the name of the message/service,
                                i.e. 'std_msgs/Int32'.
            @type  clsName:     str
            
            @param msgID:       Message ID which can be used to get a
                                correspondence between request and response
                                message for a service call.
            @type  msgID:       str
            
            @param msg:         Message which should be sent. It has to be a
                                JSON compatible dictionary where part or the
                                complete message can be replaced by a StringIO
                                instance which is interpreted as binary data.
            @type  msg:         {str : {} / base_types / StringIO} / StringIO
        """
        try:
            self._interfaces[iTag].receive(clsName, msgID, msg)
        except (DeadReferenceError, PBConnectionLost):
            raise DeadConnection()
    
    def sendToClient(self, iTag, msgType, msgID, msg):
        """ Process a data message which has been received from an interface
            send the message to the registered connection.
                            
            @param iTag:        Tag which is used to identify the interface
                                from which this message was sent.
            @type  iTag:        str
            
            @param clsName:     Message type/Service type consisting of the
                                package and the name of the message/service,
                                i.e. 'std_msgs/Int32'.
            @type  clsName:     str
            
            @param msgID:       Message ID which can be used to get a
                                correspondence between request and response
                                message for a service call.
            @type  msgID:       str
            
            @param msg:         Message which should be sent. It has to be a
                                JSON compatible dictionary where part or the
                                complete message can be replaced by a StringIO
                                instance which is interpreted as binary data.
            @type  msg:         {str : {} / base_types / StringIO} / StringIO
        """
        if not self._connection:
            # TODO: What exactly?
            return
        
        self._connection.sendDataMessage(iTag, msgType, msgID, msg)
    
    def registerConnectionToRobot(self, connection):
        """ Register the connection to the robot with this avatar.
            
            @param connection:  Connection which should be registered.
        """
        self._connection = connection
        self._client.connectionEstablished(self)
    
    def unregisterConnectionToRobot(self):
        """ Unregister the connection to the robot with this avatar.
        """
        self._connection = None
        self._client.connectionLost(self)
    
    def remote_createInterface(self, uid, iType, msgType, tag):
        """ Create an Interface object in the robot namespace and therefore in
            the endpoint.
            
            @param uid:         Unique ID which is used to identify the
                                interface in the internal communication.
            @type  uid:         str
            
            @param iType:       Type of the interface encoded as an integer.
                                Refer to rce.slave.interface.Types for more
                                information.
            @type  IType:       int
            
            @param clsName:     Message type/Service type consisting of the
                                package and the name of the message/service,
                                i.e. 'std_msgs/Int32'.
            @type  clsName:     str
            
            @param tag:         Unique ID which is used to identify the
                                interface in the external communication.
            @type  tag:         str
            
            @return:            New Interface instance.
            @rtype:             rce.master.network.Interface
                                (subclass of rce.master.base.Proxy)
        """
        return self._MAP[iType](self, UUID(bytes=uid), msgType, tag)
    
    def registerInterface(self, interface):
        # "Special" method to account for 'dict' instead of standard 'set'
        tag = interface.tag
        
        assert tag not in self._interfaces
        self._interfaces[tag] = interface
    
    def unregisterInterface(self, interface):
        # "Special" method to account for 'dict' instead of standard 'set'
        tag = interface.tag
        
        assert tag in self._interfaces
        del self._interfaces[tag]
    
    def remote_destroy(self):
        """ Method should be called to destroy the robot and will take care
            of destroying all objects owned by this robot as well as
            deleting all circular references.
        """
        if self._connection:
            self._connection.dropConnection()
        
        # The following replaces the call to Namespace.__init__()
        for interface in self._interfaces.values():
            interface.remote_destroy()
        
        assert len(self._interfaces) == 0
        assert self._connection is None
        
        self._client.unregisterRobot(self)


class RobotClient(Endpoint):
    """ Realm as well as Credentials Checker for the twisted cred system which
        is used for the connections to the robots. It is responsible for
        storing all robots (namespaces).
    """
    implements(IRealm, ICredentialsChecker)
    
    credentialInterfaces = (IRobotCredentials,)
    
    RECONNECT_TIMEOUT = 10
    
    def __init__(self, reactor, commPort):
        """ Initialize the Robot Client.
            
            @param reactor:     Reference to the twisted reactor used in this
                                robot process.
            @type  reactor:     twisted::reactor
            
            @param commPort:    Port where the server for the cloud engine
                                internal communication will listen for incoming
                                connections.
            @type  commPort:    int
        """
        Endpoint.__init__(self, reactor, commPort)
        
        self._robots = set()
        self._pendingRobots = {}
        self._deathCandidates = {}
    
    def registerRobot(self, robot):
        assert robot not in self._robots
        self._robots.add(robot)
        
        # Add the robot also to the death list
        assert robot not in self._deathCandidates
        deathCall = self._reactor.callLater(self.RECONNECT_TIMEOUT,
                                            self._killRobot, robot)
        self._deathCandidates[robot] = deathCall
    
    def unregisterRobot(self, robot):
        assert robot in self._robots
        self._robots.remove(robot)
        
        # Remove the robot also from the death list
        deathCall = self._deathCandidates.pop(robot, None)
        
        if deathCall:
            deathCall.cancel()
    
    def _killRobot(self, robot):
        """ Internally used method to destroy a robot whose reconnect timeout
            was reached.
            
            @param robot:       Robot which should be destroyed.
            @type  robot:       rce.robot.Robot
        """
        assert robot in self._deathCandidates
        del self._deathCandidates[robot]
        robot.remote_destroy()
    
    def connectionLost(self, robot):
        """ Method is used by the Robot to signal to the client that he lost
            the connection and should be marked for destruction.
            
            @param robot:       Robot which should be added to death list.
            @type  robot:       rce.robot.Robots
        """
        assert robot not in self._deathCandidates
        deathCall = self._reactor.callLater(self.RECONNECT_TIMEOUT,
                                            self._killRobot, robot)
        self._deathCandidates[robot] = deathCall
    
    def connectionEstablished(self, robot):
        """ Method is used by the Robot to signal to the client that he has
            a connection again and should be removed from the list of marked
            robots.
            
            @param robot:       Robot which should be removed from death list.
            @type  robot:       rce.robot.Robots
        """
        assert robot in self._deathCandidates
        self._deathCandidates.pop(robot).cancel()
    
    def requestAvatar(self, avatarId, mind, *interfaces):
        """ Returns an avatar for the websocket connection to the robot.
            
            Has to be implemented for twisted::IRealm.
            
            @return:            Avatar for websocket connection to the robot.
                                (type: rce.robot.Robot)
            @rtype:             twisted::Deferred
        """
        if IRobot not in interfaces:
            raise NotImplementedError('RobotClient only handles IRobot.')
        
        try:
            robot = self._pendingRobots.pop(avatarId)[1]
        except KeyError:
            raise InternalError('There is no avatar matching the ID.')
        
        return IRobot, robot, robot.remote_destroy
    
    def _passwordMatch(self, matched, avatarId):
        """ Internally used method to check whether the supplied key matched.
            Return the avatar ID on success; otherwise return an error.
        """
        if matched:
            return avatarId
        else:
            return Failure(UnauthorizedLogin())

    def requestAvatarId(self, credentials):
        """ Check if the supplied credentials are valid.
            
            Has to be implemented for twisted::ICredentialsChecker.
            
            @return:            Avatar ID if the authentication is successful.
                                (type: str)
            @rtype:             twisted::Deferred
        """
        avatarId = (credentials.userID, credentials.robotID)
        
        if avatarId in self._pendingRobots:
            d = maybeDeferred(credentials.checkKey,
                              self._pendingRobots[avatarId][0])
            return d.addCallback(self._passwordMatch, avatarId)
        else:
            return fail(UnauthorizedLogin())
    
    def remote_createNamespace(self, user, userID, robotID, key):
        """ Create a Robot namespace.
            
            @param user:        User instance to which this namespace belongs
                                and which provides the necessar callbacks for
                                the Robot Avatar.
            @type  user:        twisted.spread.pb.RemoteReference
            
            @param userID:      ID of the user which owns the robot.
            @type  userID:      str
            
            @param robotID:     ID of the robot which has to be created.
            @type  robotID:     str
            
            @param uid:         Key which will be used to authenticate the
                                webscoket connection.
            @type  uid:         str
            
            @return:            Reference to the newly created robot.
            @rtype:             rce.robot.Robot
        """
        uid = (userID, robotID)
        
        if uid in self._pendingRobots:
            raise InternalError('Can not create the same robot twice.')
        
        robot = Robot(self, user)
        self._pendingRobots[uid] = key, robot
        return robot
    
    def terminate(self):
        """ Method should be called to destroy all robots before the reactor
            is stopped.
        """
        self._pendingRobots = {}
        
        for robot in self._robots.copy():
            robot.remote_destroy()
        
        assert len(self._robots) == 0
        assert len(self._deathCandidates) == 0
        
        Endpoint.terminate(self)


def main(reactor, cred, masterIP, masterPort, extPort, commPort):
    log.startLogging(sys.stdout)
    
    def _err(reason):
        print(reason)
        reactor.stop()
    
    factory = PBClientFactory()
    reactor.connectTCP(masterIP, masterPort, factory)
    
    client = RobotClient(reactor, commPort)
    d = factory.login(cred, client)
    d.addCallback(lambda ref: setattr(client, '__ref', ref))
    d.addErrback(_err)
    
    portal = Portal(client, (client,))
    robot = CloudEngineWebSocketFactory(portal,
                                        'ws://localhost:{0}'.format(extPort))
    listenWS(robot)
    
    reactor.addSystemEventTrigger('before', 'shutdown', client.terminate)
    reactor.run()
