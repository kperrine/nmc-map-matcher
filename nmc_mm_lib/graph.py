"""
graph.py: Links and nodes for graph models; also a rudimentary breadth-first search.
@author: Kenneth Perrine
@contact: kperrine@utexas.edu
@organization: Network Modeling Center, Center for Transportation Research,
    Cockrell School of Engineering, The University of Texas at Austin 
@version: 1.0

@copyright: (C) 2014, The University of Texas at Austin
@license: GPL v3

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
from __future__ import print_function
import linear, gps, sys, math, operator
from collections import deque

class GraphLink:
    """
    GraphLink is a link that connects one node to another.
    """
    def __init__(self, ident, origNode, destNode):
        """
        @type ident: int
        @type origNode: GraphNode
        @type destNode: GraphNode 
        """
        self.id = ident
        self.origNode = origNode
        self.destNode = destNode
        
        # Placeholders for efficiency of measurement:
        self.distance = 0.0
        self.uid = -1
        
    def isComplementary(self, otherLink):
        """
        Return True if the given link directly flows in the opposite direction of this link.
        @type otherLink: GraphLink
        """
        return otherLink.destNode is self.origNode and otherLink.origNode is self.destNode

class GraphNode:
    """
    GraphNode is a node that connects multiple links together.
    """
    def __init__(self, ident, gpsLat, gpsLng):
        """
        @type ident: int
        @type gpsLat: float
        @type gpsLng: float
        """
        self.id = ident
        self.gpsLat = gpsLat
        self.gpsLng = gpsLng
        self.outgoingLinkMap = {}
        "@type self.outgoingLinkMap: dict<int, GraphLink>" 
        
        # Placeholders for coordinates in feet; these won't be filled out until this is added to the GraphLib.
        self.coordX = 0.0
        self.coordY = 0.0

class PointOnLink:
    """
    PointOnLink is a specific point on a link.  This is documented in Figure 1 of Perrine, et al. 2015
    as "point_on_link".
    
    @ivar link: "L", the link that corresponds with this PointOnLink
    @type link: GraphLink
    @ivar dist: "d", the distance along the link from the origin in feet
    @type dist: float
    @ivar nonPerpPenalty: "not r", true if there is to be a non-perpendicular penalty applied
    @type nonPerpPenalty: bool
    @ivar refDist: "d_r", the reference distance, or the working radius from the original search point
    @type refDist: float
    @ivar pointX: The point x-coordinate
    @type pointX: float
    @ivar pointY: The point y-coordinate
    @type pointY: float
    """
    def __init__(self, link, dist, nonPerpPenalty = False, refDist = 0.0):
        """
        @type link: GraphLink
        @type dist: float
        @type nonPerpPenalty: bool
        @type refDist: float
        """
        self.link = link
        self.dist = dist
        self.nonPerpPenalty = nonPerpPenalty
        self.refDist = refDist
        
        if link is not None:
            if link.distance == 0:
                dist = 0
                norm = 1
            else:
                norm = link.distance
            
            self.pointX = link.origNode.coordX + (link.destNode.coordX - link.origNode.coordX) * dist / norm
            self.pointY = link.origNode.coordY + (link.destNode.coordY - link.origNode.coordY) * dist / norm
        else:
            self.pointX = 0
            self.pointY = 0
                
class GraphLib:
    """
    GraphLib is the container that holds an entire graph.
    
    @ivar gps: Reference GPS center coordinates plus calculator
    @type gps: gps.GPS
    @ivar nodeMap: Collection of nodes if we are creating a graph-based network, None if single-path.
    @type nodeMap: dict<int, GraphNode>
    @ivar linkMap: Collection of links
    @type linkMap: dict<int, GraphLink>
    @ivar prevLinkID: Previous link ID for cases where we are dealing with single-path.
    """
    def __init__(self, gpsCtrLat, gpsCtrLng, singlePath=False):
        """
        @type gpsCtrLat: float
        @type gpsCtrLng: float
        """
        self.gps = gps.GPS(gpsCtrLat, gpsCtrLng)
        if not singlePath:
            self.nodeMap = {}
        else:
            self.nodeMap = None
        self.linkMap = {}
        self.prevLinkID = 0

    def addNode(self, node):
        """
        addNode adds a node to the GraphLib and translates its coordinates to feet. Not supported for single-path.
        @type node: GraphNode
        """
        if self.nodeMap is not None:
            (node.coordX, node.coordY) = self.gps.gps2feet(node.gpsLat, node.gpsLng)
            self.nodeMap[node.id] = node
        
    def addLink(self, link):
        """
        addLink adds a link to the GraphLib and updates its respective nodes.  Call 
        addNode first.
        @type link: GraphLink
        @return the unique ID for the link
        """
        if self.nodeMap is not None and link.origNode.id not in self.nodeMap:
            print('WARNING: Node %d is not present.' % link.origNode, file = sys.stderr)
            return
        link.distance = linear.getNorm(link.origNode.coordX, link.origNode.coordY, link.destNode.coordX, link.destNode.coordY)
        if self.nodeMap is not None:
            ourID = link.id
            link.uid = link.id
            self.prevLinkID = link.id
        else:
            ourID = self.prevLinkID
            link.uid = self.prevLinkID
            self.prevLinkID += 1
        self.linkMap[ourID] = link
        link.origNode.outgoingLinkMap[link.id] = link
        return link.uid
        
    def findPointsOnLinks(self, pointX, pointY, radius, primaryRadius, secondaryRadius, prevPoints, limitClosestPoints = sys.maxint):
        """
        findPointsOnLinks searches through the graph and finds all PointOnLinks that are within the radius.
        Then, eligible links are proposed primaryRadius distance around the GTFS point, or secondaryRadius
        distance from the previous VISTA points.  Returns an empty list if none are found.  This corresponds
        with algorithm "FindPointsOnLinks" in Figure 1 of Perrine, et al. 2015.
        @type pointX: float
        @type pointY: float
        @type radius: float
        @type primaryRadius: float
        @type secondaryRadius: float
        @type prevPoints: list<PointOnLink>
        @type limitClosestPoints: int
        @rtype list<PointOnLink>
        """
        # TODO: This brute-force implementation can be more efficient with quad trees, etc. rather than
        # scanning through all elements.
        radiusSq = radius ** 2
        primaryRadiusSq = primaryRadius ** 2
        secondaryRadiusSq = secondaryRadius ** 2
        retSet = set()
        
        # Find perpendicular and non-perpendicular PointOnLinks that are within radius.
        for link in self.linkMap.values():
            "@type link: graph.GraphLink"
            (distSq, linkDist, perpendicular) = linear.pointDistSq(pointX, pointY, link.origNode.coordX, link.origNode.coordY,
                                                                   link.destNode.coordX, link.destNode.coordY, link.distance)
            if distSq <= radiusSq:
                pointOnLink = PointOnLink(link, linkDist, not perpendicular, math.sqrt(distSq))
                
                # We are within the initial search radius.  Are we then within the primary radius?
                if distSq <= primaryRadiusSq:
                    # Yes, easy.  Add to the list:
                    retSet.add(pointOnLink)
                else:
                    # Check to see if the point is close to a previous point:
                    for prevPoint in prevPoints:
                        "@type prevPoint: PointOnLink"
                        distSq = linear.getNormSq(pointOnLink.pointX, pointOnLink.pointY, prevPoint.pointX, prevPoint.pointY)
                        if (distSq < secondaryRadiusSq):
                            # We have a winner:
                            retSet.add(pointOnLink)
                            break
                   
        # Filter out duplicate locations represented by a nonperpendicular match to the end of one link and a nonperpendicular
        # match to the start of the following link. Keep the upstream one:
        nonPerpSetStarts = {}
        nonPerpSetEnds = set()
        for pointOnLink in retSet:
            if pointOnLink.nonPerpPenalty:
                if pointOnLink.dist == 0:
                    if pointOnLink.link.origNode not in nonPerpSetStarts:
                        nonPerpSetStarts[pointOnLink.link.origNode] = set()
                    nonPerpSetStarts[pointOnLink.link.origNode].add(pointOnLink)
                elif pointOnLink.dist == pointOnLink.link.distance:
                    nonPerpSetEnds.add(pointOnLink)
        for endingPointOnLink in nonPerpSetEnds:
            if endingPointOnLink.link.destNode in nonPerpSetStarts:
                for pointOnLink in nonPerpSetStarts[endingPointOnLink.link.destNode]:
                    if endingPointOnLink.refDist == pointOnLink.refDist:
                        if pointOnLink in retSet:
                            retSet.remove(pointOnLink) 
                    
        ret = list(retSet)
        
        # Keep limited number of closest values 
        ret.sort(key = operator.attrgetter('refDist'))
        return ret[0:limitClosestPoints]

class WalkPathProcessor:
    """
    WalkPathProcessor contains methods used to conduct the walkPath algorithm.  It maintains a cache that
    persists in-between individual pathfinding operations.
    
    @ivar pathEngine: A reference to the object that instanciates this class.
    @type pathEngine: path_engine.PathEngine
    @ivar backCache: Caches previous walkPath operations to accelerate processing a little bit 
    @type backCache: dict<int, dict<int, GraphLink>>
    @ivar winner: Records the winning queue element 
    @type winner: _WalkPathNext
    @ivar processingQueue: Processing queue to facilitate the breadth-first search
    @type processingQueue: deque
    @ivar pointOnLinkOrig: For internal record-keeping    
    @type pointOnLinkOrig: PointOnLink
    @ivar pointOnLinkDest: For internal record-keeping
    @type pointOnLinkDest: PointOnLink
    """        
    def __init__(self, pathEngine, limitRadius, limitDistance, limitRadiusRev, limitSteps, allowUTurns=True):
        """
        This sets the parameters that are final for the entire walkPath algorithm execution:
        @type pathEngine: path_engine.PathEngine
        @type limitRadius: float
        @type limitDistance: float
        @type limitRadiusRev: float
        @type limitSteps: int
        @type allowUTurns: bool
        """
        self.pathEngine = pathEngine
        self.limitDistance = limitDistance
        self.limitRadiusRev = limitRadiusRev
        self.limitSteps = limitSteps

        self.limitRadius = limitRadius
        self.limitRadiusSq = (limitRadius ** 2) if limitRadius < sys.float_info.max else sys.float_info.max

        # walkPath cache:
        self.backCache = {}
        self.allowUTurns = allowUTurns
        
        # Keep the running score:
        self.backtrackScore = limitDistance
        
        # Record the winning queue element:
        self.winner = None
        
        # Other variables that exist throughout pathfinding iterations:
        self.processingQueue = None
        self.pointOnLinkOrig = None
        self.pointOnLinkDest = None
        self.taskNumber = 0
        
    class _WalkPathNext:
        """
        _WalkPathNext allows path match requests to be queued. Each of these represents a traversal from the
        start of incomingLink to the starts of the next possible links. The walkPath() method will create new
        _WalkPathNext instances for each of those possible links and enqueues them in the priority queue that
        coordinates the pathfinding operations.
        @ivar prevStruct: The previous _WalkPathNext object that represents the link traversal for the previous
            link in the path.
        @type prevStruct: _WalkPathNext
        @ivar incomingLink: The link that we are to traverse.
        @type incomingLink: GraphLink
        @ivar distance: The total distance from the origin PointOnLink to the current location.
        @type distance: float
        @ivar cost: The total calculated cost from the origin PointOnLink to the current location.
        @type cost: float
        @ivar stepCount: The number of steps traversed from the origin PointOnLink to incomingLink.
        @type stepCount: int
        @ivar backtrackSet: A set of link unique IDs for all links that had already been traversed.
        @ivar backtrackSet: set<int>
        """
        def __init__(self, processor, prevStruct, incomingLink, startupCost=0.0):
            """
            This initializes the elements that are stored within this object.
            @type processor: WalkPathProcessor
            @type prevStruct: _WalkPathNext
            @type incomingLink: GraphLink
            @type startupCost: float
            """
            self.prevStruct = prevStruct
            self.incomingLink = incomingLink
            if prevStruct is None:
                # First-time initialization:
                self.distance = processor.pointOnLinkOrig.link.distance - processor.pointOnLinkOrig.dist
                self.stepCount = 0
            else:
                self.distance = prevStruct.distance + incomingLink.distance
                self.stepCount = prevStruct.stepCount + 1

            if incomingLink is processor.pointOnLinkDest.link:
                # Last-time initialization; we have hit the destination link:
                # We are stopping midway through this link.  So, subtract off the distance from the
                # end that we aren't traversing.
                self.distance -= processor.pointOnLinkDest.link.distance - processor.pointOnLinkDest.dist
                self.cost = startupCost + processor.pathEngine.scoreFunction(processor.pointOnLinkOrig, self.distance, processor.pointOnLinkDest)
            else:
                # Normal operation; we hadn't encountered the destination link yet:
                self.cost = startupCost + processor.pathEngine.scoreFunction(processor.pointOnLinkOrig, self.distance, None)

            # Establish a priority metric here, favoring a destination node straight ahead and close.
            self.dotMag = 0.0
            """
            This seems to just make the system worse.
            if incomingLink is not processor.pointOnLinkDest.link:
                oPointX, oPointY = incomingLink.origNode.coordX, incomingLink.origNode.coordY
                dPointX, dPointY = incomingLink.destNode.coordX, incomingLink.destNode.coordY
                fPointX, fPointY = processor.pointOnLinkDest.link.origNode.coordX, processor.pointOnLinkDest.link.origNode.coordY
                mag = math.sqrt((fPointX - oPointX) ** 2 + (fPointY - oPointY) ** 2) * incomingLink.distance
                if mag > 0.0001:
                    dot = ((dPointX - oPointX) * (fPointX - oPointX) + (dPointY - oPointY) * (fPointY - oPointY)) / mag
                    theta = math.acos(dot) if dot < 0.999 else 0
                    self.dotMag = theta * mag
            """
                                            
            # Make a copy of the set only if it is to change, and add in the new incoming link ID:
            oldBacktrackSet = prevStruct.backtrackSet if prevStruct is not None else set()
            "@type oldBacktrackSet: set<int>"
            if incomingLink.uid not in oldBacktrackSet: 
                self.backtrackSet = set(oldBacktrackSet)
                self.backtrackSet.add(incomingLink.uid)
            else:
                self.backtrackSet = oldBacktrackSet
    
    def walkPath(self, pointOnLinkOrig, pointOnLinkDest):
        """
        walkPath uses a breadth-first search to find the shortest distance from a given PointOnLink to another PointOnLink and
        returns a list of links representing nodes and following links encountered.  Specify a limiting radius for
        evaluating target nodes, and maximum distance traversed.  Also specify a smaller radius for small distances backwards.
        If nothing is found, then None is returned.  An empty list signifies that the destination is on the same link as the
        origin.
        @type pointOnLinkOrig: PointOnLink
        @type pointOnLinkDest: PointOnLink
        @return List of new GraphLinks traversed, distance, and cost 
        @rtype list<GraphLink>, float, float
        """
        # Initializations:
        self.pointOnLinkOrig = pointOnLinkOrig
        self.pointOnLinkDest = pointOnLinkDest
        self.winner = None
        self.backtrackScore = self.limitDistance
        self.taskNumber = 0
        
        # Are the points too far away to begin with?
        origDestDistSq = linear.getNormSq(self.pointOnLinkDest.pointX, self.pointOnLinkDest.pointY, self.pointOnLinkOrig.pointX, self.pointOnLinkOrig.pointY)
        if origDestDistSq > self.limitRadiusSq:
            return (None, 0.0, 0.0)
        
        # Set a reasonable bound for the expected distance in this path search:
        self.backtrackScore = self.limitDistance

        # Set up a queue for the search.  Preload the queue with the first starting location:
        """
        self.processingQueue = Queue.PriorityQueue()
        struct = self._WalkPathNext(self, None, self.pointOnLinkOrig.link)        
        self.processingQueue.put((struct.dotMag, self.taskNumber, struct))
        self.taskNumber += 1
        """
        self.processingQueue = deque()
        self.processingQueue.append(self._WalkPathNext(self, None, self.pointOnLinkOrig.link))
        
        # Do the breadth-first search:
        while not len(self.processingQueue) == 0:
            self._walkPath(self.processingQueue.popleft())
        """
        while not self.processingQueue.empty():
            _, _, struct = self.processingQueue.get_nowait()
            self._walkPath(struct)
        """
        
        # Set up the return:
        if self.winner is not None:
            # Iterate through all of the links we have traversed. (Ignore first item because we
            # hadn't technically traversed it).
            retList = []
            "@type retList: list<GraphLink>"
            element = self.winner
            "@type element: _WalkPathNext"
            while element.prevStruct is not None:
                retList.append(element.incomingLink)
                element = element.prevStruct
            retList.reverse()
            return (retList, self.winner.distance, self.winner.cost)
        else:
            # We didn't find anything.
            return (None, 0.0, 0.0)
        
    # _walkPath is called internally by walkPath().
    def _walkPath(self, walkPathElem):
        """
        _walkPath is the internal processing element for the pathfinder.
        @type walkPathElem: _WalkPathNext
        """
        # Check maximum number of steps:
        if walkPathElem.stepCount >= self.limitSteps:
            return
        
        # Check total distance; we are not interested if we exceed our previous best score:
        if walkPathElem.distance >= self.backtrackScore:
            return
        
        # Do we exceed the worst cost in the list of simultaneous costs?
        if self.pathEngine.exceedsPreviousCosts(walkPathElem.cost):
            return
                    
        # Are we at the destination?
        if walkPathElem.incomingLink is self.pointOnLinkDest.link:
            # We have a winner!
            self.winner = walkPathElem
            self.backtrackScore = walkPathElem.distance
            
            # Log the winner into the cache by looking at all of the parent elements:
            if self.pointOnLinkDest.link.uid not in self.backCache:
                self.backCache[self.pointOnLinkDest.link.uid] = {}
            mappings = self.backCache[self.pointOnLinkDest.link.uid]
            "@type mappings: dict<int, GraphLink>"
            if walkPathElem.prevStruct is not None:
                element = walkPathElem.prevStruct
                "@type element: _WalkPathNext"
                while element.prevStruct is not None:
                    if (element.prevStruct.incomingLink.uid in mappings) \
                            and (mappings[element.prevStruct.incomingLink.uid] is element.incomingLink):
                        break
                    mappings[element.prevStruct.incomingLink.uid] = element.incomingLink
                    element = element.prevStruct
                
            # Process the next queue element:
            return
        
        # Look at each link that comes out from the current node.
        # First, see if there is a shortcut to our destination already in the cache:
        if (self.pointOnLinkDest.link.uid in self.backCache) and \
                (walkPathElem.incomingLink.uid in self.backCache[self.pointOnLinkDest.link.uid]):
            myList = [self.backCache[self.pointOnLinkDest.link.uid][walkPathElem.incomingLink.uid]]
        else:
            myList = walkPathElem.incomingLink.destNode.outgoingLinkMap.values()
        for link in myList:
            if not self.allowUTurns:
                # Filter out U-turns:
                if walkPathElem.incomingLink.isComplementary(link):
                    continue
            
            # Had we visited this before?
            if link.uid in walkPathElem.backtrackSet:
                continue
            
            # Add to the queue for processing later:
            self.processingQueue.append(self._WalkPathNext(self, walkPathElem, link))
            """
            struct = self._WalkPathNext(self, walkPathElem, link)        
            self.processingQueue.put((struct.dotMag, self.taskNumber, struct))
            self.taskNumber += 1
            """
