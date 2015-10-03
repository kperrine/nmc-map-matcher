"""
transit_gtfs.py outputs a series of CSV files in the current path that
    are used for VISTA analysis of transit paths. In short, map-matched
    transit paths are the basis for map-matched bus stops. These stops
    are mapped to the underlying VISTA network, but because of a
    limitation in VISTA, only one of these stops may be mapped to any
    one link. (Extra stops for the time being are dropped).
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
from nmc_mm_lib import gtfs, vista_network, path_engine, graph
import problem_report, sys, time
from datetime import datetime, timedelta

DWELLTIME_DEFAULT = 0
"@var DWELLTIME_DEFAULT: The dwell time to report in the bus_route_link.csv file output."

STOP_SEARCH_RADIUS = 800
"@var STOP_SEARCH_RADIUS: 'k': Radius (ft) to search from GTFS point to perpendicular VISTA links"

DISTANCE_FACTOR = 1.0
"@var DISTANCE_FACTOR: 'f_d': Cost multiplier for Linear path distance in stop matching"

DRIFT_FACTOR = 2.0
"@var DRIFT_FACTOR: 'f_r': Cost multiplier for distance from GTFS point to its VISTA link in stop matching"

NON_PERP_PENALTY = 1.5
"@var NON_PERP_PENALTY: 'f_p': Penalty multiplier for GTFS points that aren't perpendicular to VISTA links"

EMBELLISH_COUNT = 2
"""@var EMBELLISH_COUNT: The number of nodes at the beginning, and then again the number of nodes at the end
    of each path matched trip to add incoming links and outgoing links."""

EMBELLISH_DEPTH = 1
"@var EMBELLISH_DEPTH: The depth at which embellished links are added to the single bus route network."

problemReport = False
"@var problemReport is set to true when the -p parameter is specified."

def syntax(exitCode):
    """
    Print usage information
    """
    print("transit_gtfs outputs a series of CSV files in the current path that")
    print("are used for VISTA analysis of transit paths.")
    print()
    print("Usage:")
    print("  python transit_gtfs.py dbServer network user password shapePath")
    print("    pathMatchFile -t refDateTime [-e endTime] {[-c serviceID]")
    print("    [-c serviceID] ...} [-u] [-w] [-p]")
    print()
    print("where:")
    print("  -t is the zero-reference time that all arrival time outputs are related to.")
    print("     (Note that the day is ignored.) Use the format HH:MM:SS.")
    print("  -e is the duration in seconds (86400 by default). -t and -e filter stops.")
    print("  -c restricts results to specific service IDs (default: none)")
    print("  -u excludes links upstream of the first valid stop")
    print("  -w, -wb, -we: widen both, widen begin, widen end: include entire routes that")
    print("     would otherwise be cut off by -t (begin) and/or -e (end). This will")
    print("     suggest new starting time/duration and record all times relative to that.")
    print("  -x, -xb, -xe: exclude both, exclude begin, exclude end: excludes entire")
    print("     entire routes that intersect with -t (begin) and/or -e (end).")
    print("  -p outputs a problem report on the stop matches")
    sys.exit(exitCode)

def restorePathMatch(dbServer, networkName, userName, password, shapePath, pathMatchFilename):
    # Get the database connected:
    print("INFO: Connect to database...", file=sys.stderr)
    database = vista_network.connect(dbServer, userName, password, networkName)
    
    # Read in the topology from the VISTA database:
    print("INFO: Read topology from database...", file=sys.stderr)
    vistaGraph = vista_network.fillGraph(database)
    
    # Read in the shapefile information:
    print("INFO: Read GTFS shapefile...", file=sys.stderr)
    gtfsShapes = gtfs.fillShapes(shapePath, vistaGraph.gps)

    # Read the path-match file:
    print("INFO: Read the path-match file '%s'..." % pathMatchFilename, file=sys.stderr)
    with open(pathMatchFilename, 'r') as inFile:
        gtfsNodes = path_engine.readStandardDump(vistaGraph, gtfsShapes, inFile)
        "@type gtfsNodes: dict<int, list<path_engine.PathEnd>>"

    # Filter out the unused shapes:
    unusedShapeIDs = set()
    for shapeID in gtfsShapes.keys():
        if shapeID not in gtfsNodes:
            del gtfsShapes[shapeID]
            unusedShapeIDs.add(shapeID)

    return (vistaGraph, gtfsShapes, gtfsNodes, unusedShapeIDs)

def _outHeader(tableName, userName, networkName, outFile):
    print("User,%s" % userName, file = outFile)
    print("Network,%s" % networkName, file = outFile)
    print("Table,public.bus_route", file = outFile)
    print(time.strftime("%a %b %d %H:%M:%S %Y"), file = outFile)
    print(file = outFile)

def dumpBusRoutes(gtfsTrips, userName, networkName, outFile = sys.stdout):
    """
    dumpBusRoutes dumps out a public.bus_route.csv file contents.
    @type gtfsTrips: dict<int, gtfs.TripsEntry>
    @type userName: str
    @type networkName: str
    @type outFile: file
    """
    _outHeader("public.bus_route", userName, networkName, outFile)
    print("\"id\",\"name\",", file = outFile)
    
    # Remember, we are treating each route as a trip.
    tripIDs = gtfsTrips.keys()
    tripIDs.sort()
    for tripID in tripIDs:
        append = ""
        if len(gtfsTrips[tripID].route.name) > 0:
            append = ": " + gtfsTrips[tripID].route.name
        if len(gtfsTrips[tripID].tripHeadsign) > 0:
            append += " " + gtfsTrips[tripID].tripHeadsign
        print("\"%d\",\"%s\"" % (tripID, gtfsTrips[tripID].route.shortName + append),
                file = outFile)

def treeContiguous(treeNodes, vistaNetwork, gtfsStopTimes=None, startTime=None, endTime=None):
    """
    treeContiguous finds the largest consecutive string of continuous points that fall within the
    given time range (if given). Used by dumpBusRouteLinks() and possibly others.
    @type treeNodes: list<path_engine.PathEnd>
    @type vistaNetwork: graph.GraphLib
    @type gtfsStopTimes: list<gtfs.StopTimesEntry>
    @type startTime: datetime
    @type endTime: datetime
    @return A list of tree entries that are extracted from the given shape, or None if failure.
    @rtype (list<path_engine.PathEnd>, int)
    """
    startIndex = -1
    curIndex = 0
    linkCount = 0
    totalLinks = 0
    
    longestStart = -1
    longestEnd = len(treeNodes)
    longestDist = sys.float_info.min
    longestLinkCount = 0
    
    while curIndex <= len(treeNodes):
        if curIndex == len(treeNodes) or curIndex == 0 or treeNodes[curIndex].restart:
            totalLinks += 1
            linkCount += 1
            if curIndex > startIndex and startIndex >= 0:
                # We have a contiguous interval.  See if it wins:
                if treeNodes[curIndex - 1].totalDist - treeNodes[startIndex].totalDist > longestDist:
                    longestStart = startIndex
                    longestEnd = curIndex
                    longestDist = treeNodes[curIndex - 1].totalDist - treeNodes[startIndex].totalDist
                    longestLinkCount = linkCount
                    linkCount = 0
                
            # This happens if it is time to start a new interval:
            startIndex = curIndex
        else:
            totalLinks += len(treeNodes[curIndex].routeInfo)
            linkCount += len(treeNodes[curIndex].routeInfo)
        curIndex += 1

    if longestStart >= 0:
        # We have a valid path.  See if it had been trimmed down and report it.
        if longestStart > 0 or longestEnd < len(treeNodes):
            print("WARNING: For shape ID %s from seq. %d through %d, %.2g%% of %d links will be used used because of restarts in the path match file.." \
                  % (str(treeNodes[longestStart].shapeEntry.shapeID), treeNodes[longestStart].shapeEntry.shapeSeq,
                     treeNodes[longestEnd - 1].shapeEntry.shapeSeq, 100 * float(longestLinkCount) / float(totalLinks),
                     totalLinks), file=sys.stderr)
        
        # Ignore routes that are entirely outside our valid time interval.
        flag = False
        if gtfsStopTimes is None:
            flag = True
        else:
            if len(gtfsStopTimes) == 0:
                # This will happen if we don't have stops defined. In this case, we want to go ahead and process the bus_route_link
                # outputs because we don't know if the trip falls in or out of the valid time range.
                flag = True
            else:
                for stopEntry in gtfsStopTimes:
                    if (startTime is None or stopEntry.arrivalTime >= startTime) and (endTime is None or stopEntry.arrivalTime <= endTime):
                        flag = True
                        break
        if not flag:
            # This will be done silently because (depending upon the valid interval) there could be
            # hundreds of these in a GTFS set.
            return None, 0
        
        # Isolate the relevant VISTA tree nodes: (Assume from above that this is a non-zero length array)
        return treeNodes[longestStart:longestEnd], longestStart
    
    else:
        print("WARNING: No links for shape %s." % str(treeNodes[longestStart].shapeEntry.shapeID), file=sys.stderr)
        return None, 0

def buildSubset(treeNodes, vistaNetwork):
    """
    buildSubset builds a tree from a shape. Used by dumpBusRouteLinks() and possibly others.
    @type treeNodes: list<path_engine.PathEnd>
    @type vistaNetwork: graph.GraphLib
    @return The network subset and list of link IDs
    @rtype (graph.GraphLib, list<graph.GraphLink>)
    """
    # We are going to recreate a small VISTA network from ourGTFSNodes and then match up the stops to that.
    # First, prepare the small VISTA network:
    subset = graph.GraphLib(vistaNetwork.gps.latCtr, vistaNetwork.gps.lngCtr, True)
    
    # Build a list of links:
    outLinkList = []
    "@type outLinkList: list<graph.GraphLink>"
    
    # Plop in the start node:
    subsetNodePrior = graph.GraphNode(treeNodes[0].pointOnLink.link.origNode.id,
        treeNodes[0].pointOnLink.link.origNode.gpsLat, treeNodes[0].pointOnLink.link.origNode.gpsLng)
    "@type subsetNodePrior: graph.GraphNode"
    subsetNodePrior.coordX, subsetNodePrior.coordY = treeNodes[0].pointOnLink.link.origNode.coordX, treeNodes[0].pointOnLink.link.origNode.coordY
    prevLinkID = treeNodes[0].pointOnLink.link.id
    
    # Link together nodes as we traverse through them:
    for ourGTFSNode in treeNodes:
        "@type ourGTFSNode: path_engine.PathEnd"
        # There should only be one destination link per VISTA node because this comes form our tree.
        # If there is no link or we're repeating the first one, then there were no new links assigned.
        if len(ourGTFSNode.routeInfo) < 1 or (len(outLinkList) == 1 \
                and ourGTFSNode.routeInfo[0].id == treeNodes[0].pointOnLink.link.id):
            continue
        for link in ourGTFSNode.routeInfo:
            "@type link: graph.GraphLink"
        
            if link.id not in vistaNetwork.linkMap:
                print("WARNING: In finding bus route links, link ID %d is not found in the VISTA network." % link.id, file=sys.stderr)
                continue
            origVistaLink = vistaNetwork.linkMap[link.id]
            "@type origVistaLink: graph.GraphLink"
            
            # Create a new node, even if the node had been visited before. We are creating a single-path and need a separate instance:
            subsetNode = graph.GraphNode(origVistaLink.origNode.id, origVistaLink.origNode.gpsLat, origVistaLink.origNode.gpsLng)
            subsetNode.coordX, subsetNode.coordY = origVistaLink.origNode.coordX, origVistaLink.origNode.coordY
            # We don't add nodes to single-path graphs.
                
            # We shall label our links as indices into the stage we're at in ourGTFSNodes links.  This will allow for access later.
            newLink = graph.GraphLink(prevLinkID, subsetNodePrior, subsetNode)
            subset.addLink(newLink)
            outLinkList.append(newLink)
            subsetNodePrior = subsetNode
            prevLinkID = link.id
            
    # And then finish off the graph with the last link:
    subsetNode = graph.GraphNode(ourGTFSNode.pointOnLink.link.destNode.id, ourGTFSNode.pointOnLink.link.destNode.gpsLat, ourGTFSNode.pointOnLink.link.destNode.gpsLng)
    subsetNode.coordX, subsetNode.coordY = ourGTFSNode.pointOnLink.link.destNode.coordX, ourGTFSNode.pointOnLink.link.destNode.coordY
    newLink = graph.GraphLink(prevLinkID, subsetNodePrior, subsetNode)
    subset.addLink(newLink)
    outLinkList.append(newLink)
    
    return subset, outLinkList

def embellishSubset(subset, linkList, vistaNetwork, embellishCount=EMBELLISH_COUNT, embellishDepth=EMBELLISH_DEPTH):
    """
    embellishSubset adds adjoining links to the start and end of the subset as defined by linkList.
    @type subset: graph.GraphLib
    @type linkList: list<graph.GraphLink>
    @type vistaNetwork: graph.GraphLib
    @type embellishCount: int
    @type embellishDepth: int
    """
    usedNodes = {}
    "@type usedNodes: dict<int, graph.GraphNode>"
    usedLinkIDs = set() # We keep a separate set of these rather than using the ones in subset linkMap because
                        # the one in linkMap is referred by uid's, whereas we pick the first encountered ID
                        # in this case (or last encountered on the other end) because of the possibility of
                        # there being repeated visits to nodes and links because of looping. 
    "@type usedLinkIDs: set<int>"
    if len(linkList) > 0:
        usedNodes[linkList[0].origNode.id] = linkList[0].origNode 
    midpoint = len(linkList) / 2
    # Add the beginning in forward order in case connections are duplicate nodes because of loops.
    for index in range(0, midpoint):
        if linkList[index].destNode.id not in usedNodes:
            usedNodes[linkList[index].destNode.id] = linkList[index].destNode
            usedLinkIDs.add(linkList[index].id)
    # Add the ending in reverse order for the same reason.
    for index in range(len(linkList) - 1, midpoint - 1, -1):
        if linkList[index].destNode.id not in usedNodes:
            usedNodes[linkList[index].destNode.id] = linkList[index].destNode
            usedLinkIDs.add(linkList[index].id)

    # TODO: Consider adding incomingLinkMap lists to all GraphNodes, then we don't have to build this nodeLinkMap.
    # As it is, it is run on each trip and assembles together the exact same data each time. 
    nodeLinkMap = {} # This is the map that allows one to know all of the links that enter into a node.
                        # This is node ID mapped to list of incoming link IDs.
    "@type nodeLinkMap: dict<int, list<int>>"
    for vistaLink in vistaNetwork.linkMap.itervalues():
        "@type vistaLink: graph.GraphLink"
        if vistaLink.destNode.id not in nodeLinkMap:
            nodeLinkMap[vistaLink.destNode.id] = []
        nodeLinkMap[vistaLink.destNode.id].append(vistaLink.id)
    
    # Now, add in the new connecting nodes coming into the starting nodes:
    for index in range(0, min(len(linkList), embellishCount)):
        _embellishIn(subset, vistaNetwork, linkList[index].origNode.id, embellishDepth, usedNodes, usedLinkIDs, nodeLinkMap)
    # Then, add in the new connecting nodes leaving from the ending nodes:
    for index in range(len(linkList) - 1, max(-1, len(linkList) - 1 - embellishCount), -1):
        _embellishOut(subset, vistaNetwork, linkList[index].destNode.id, embellishDepth, usedNodes, usedLinkIDs)
    
def _embellishIn(subset, vistaNetwork, nodeID, curDepth, usedNodes, usedLinkIDs, nodeLinkMap):
    """
    Internal function called by embellishSubset() that begins at subsetNode and performs
    the addition of joining links in the incoming direction. If curDepth >= 1 then this function is called recursively.
    @type subset: graph.GraphLib
    @type vistaNetwork: graph.GraphLib
    @type nodeID: int
    @type curDepth: int
    @type usedNodes: dict<int, graph.GraphNode>
    @type usedLinkIDs: set<int>
    @type nodeLinkMap: dict<int, list<int>>
    """
    if curDepth <= 0:
        return
    if nodeID not in nodeLinkMap:
        # This happens when we have a node that only has outgoing links.
        return
    for linkID in nodeLinkMap[nodeID]:
        if linkID not in usedLinkIDs:
            vistaLink = vistaNetwork.linkMap[linkID]
            if vistaLink.origNode.id not in usedNodes:
                subsetOrigNode = graph.GraphNode(vistaLink.origNode.id, vistaLink.origNode.gpsLat, vistaLink.origNode.gpsLng)
                subsetOrigNode.coordX, subsetOrigNode.coordY = vistaLink.origNode.coordX, vistaLink.origNode.coordY
                usedNodes[subsetOrigNode.id] = subsetOrigNode
            else:
                subsetOrigNode = usedNodes[vistaLink.origNode.id] 
            subsetLink = graph.GraphLink(linkID, subsetOrigNode, usedNodes[nodeID])
            subset.addLink(subsetLink)
            usedLinkIDs.add(linkID)
            _embellishIn(subset, vistaNetwork, subsetOrigNode.id, curDepth - 1, usedNodes, usedLinkIDs, nodeLinkMap)

def _embellishOut(subset, vistaNetwork, nodeID, curDepth, usedNodes, usedLinkIDs):
    """
    Internal function called by embellishSubset() that begins at subsetNode and performs
    the addition of joining links in the outgoing direction. If curDepth >= 1 then this function is called recursively.
    @type subset: graph.GraphLib
    @type vistaNetwork: graph.GraphLib
    @type nodeID: int
    @type curDepth: int
    @type usedNodes: dict<int, graph.GraphNode>
    @type usedLinkIDs: set<int>
    """
    if curDepth <= 0:
        return
    for vistaLink in vistaNetwork.nodeMap[nodeID].outgoingLinkMap.itervalues():
        if vistaLink.id not in usedLinkIDs:
            if vistaLink.destNode.id not in usedNodes:
                subsetDestNode = graph.GraphNode(vistaLink.destNode.id, vistaLink.destNode.gpsLat, vistaLink.destNode.gpsLng)
                subsetDestNode.coordX, subsetDestNode.coordY = vistaLink.destNode.coordX, vistaLink.destNode.coordY
                usedNodes[subsetDestNode.id] = subsetDestNode
            else:
                subsetDestNode = usedNodes[vistaLink.destNode.id] 
            subsetLink = graph.GraphLink(vistaLink.id, usedNodes[nodeID], subsetDestNode)
            subset.addLink(subsetLink)
            usedLinkIDs.add(vistaLink.id)
            _embellishOut(subset, vistaNetwork, subsetDestNode.id, curDepth - 1, usedNodes, usedLinkIDs)

def prepareMapStops(treeNodes, stopTimes, dummyFlag=True):
    """
    prepareMapStops maps stops information to an underlying path. Used by dumpBusRouteLinks() and possibly others.
    @type treeNodes: list<path_engine.PathEnd>
    @type stopTimes: list<gtfs.StopTimesEntry>
    @param dummyFlag: Set to true to add dummy entries to the start and end. This will allow proximity searching at these places.
    @type dummyFlag: bool
    @return Prepared stop information
    @rtype (list<gtfs.ShapesEntry>, dict<int, gtfs.StopTimesEntry>)
    """
    gtfsShapes = []
    gtfsStopsLookup = {}
    "@type gtfsStopsLookup: dict<int, gtfs.StopTimesEntry>"
    
    if dummyFlag:
        # Append an initial dummy shape to force routing through the path start:
        newShapesEntry = gtfs.ShapesEntry(stopTimes[0].trip.tripID, -1, treeNodes[0].pointOnLink.link.origNode.gpsLat,
            treeNodes[0].pointOnLink.link.origNode.gpsLng)
        newShapesEntry.pointX, newShapesEntry.pointY = treeNodes[0].pointOnLink.link.origNode.coordX, treeNodes[0].pointOnLink.link.origNode.coordY
        gtfsShapes.append(newShapesEntry)
    
    # Append all of the stops:
    for gtfsStopTime in stopTimes:
        "@type gtfsStopTime: gtfs.StopTimesEntry"
        newShapesEntry = gtfs.ShapesEntry(gtfsStopTime.trip.tripID, gtfsStopTime.stopSeq, gtfsStopTime.stop.gpsLat, gtfsStopTime.stop.gpsLng)
        newShapesEntry.pointX, newShapesEntry.pointY = gtfsStopTime.stop.pointX, gtfsStopTime.stop.pointY
        gtfsShapes.append(newShapesEntry)
        gtfsStopsLookup[gtfsStopTime.stopSeq] = gtfsStopTime

    if dummyFlag:
        # Append a trailing dummy shape to force routing through the path end:
        newShapesEntry = gtfs.ShapesEntry(stopTimes[0].trip.tripID, -1, treeNodes[-1].pointOnLink.link.destNode.gpsLat,
            treeNodes[-1].pointOnLink.link.destNode.gpsLng)
        newShapesEntry.pointX, newShapesEntry.pointY = treeNodes[-1].pointOnLink.link.destNode.coordX, treeNodes[-1].pointOnLink.link.destNode.coordY
        gtfsShapes.append(newShapesEntry)

    return gtfsShapes, gtfsStopsLookup

def assembleProblemReport(resultTree, vistaNetwork):
    """
    assembleProblemReport puts together updated path_engine.PathEnd objects that are used for a problem report.
    Used by dumpBusRouteLinks() and possibly others.
    @type resultTree: list<path_engine.PathEnd>
    @type vistaNetwork: graph.GraphLib
    @rtype dict<int, path_engine.PathEnd>
    """
    revisedNodeList = {}
    prevNode = None
    "@type revisedNodeList: dict<int, path_engine.PathEnd>"
    for stopNode in resultTree:
        # Reconstruct a tree node in terms of the original network.
        # TODO: Check to make sure that resultTree[0].shapeEntry.shapeID is correct.
        newShape = gtfs.ShapesEntry(resultTree[0].shapeEntry.shapeID,
            stopNode.shapeEntry.shapeSeq, stopNode.shapeEntry.lat, stopNode.shapeEntry.lng, False)
        origLink = vistaNetwork.linkMap[stopNode.pointOnLink.link.id] 
        newPointOnLink = graph.PointOnLink(origLink, stopNode.pointOnLink.dist,
            stopNode.pointOnLink.nonPerpPenalty, stopNode.pointOnLink.refDist)
        newNode = path_engine.PathEnd(newShape, newPointOnLink)
        newNode.restart = stopNode.restart
        newNode.totalCost = stopNode.totalCost
        newNode.totalDist = stopNode.totalDist
        newNode.routeInfo = []
        for link in stopNode.routeInfo:
            newNode.routeInfo.append(vistaNetwork.linkMap[link.id])
        newNode.prevTreeNode = prevNode
        prevNode = newNode
        revisedNodeList[stopNode.shapeEntry.shapeSeq] = newNode
    return revisedNodeList 

def dumpBusRouteLinks(gtfsTrips, gtfsStopTimes, gtfsNodes, vistaNetwork, stopSearchRadius, excludeUpstream, userName,
        networkName, startTime, endTime, widenBegin, widenEnd, excludeBegin, excludeEnd, outFile=sys.stdout):
    """
    dumpBusRouteLinks dumps out a public.bus_route_link.csv file contents. This also will remove all stop times and trips
    that fall outside of the valid evaluation interval as dictated by the exclusion parameters.
    @type gtfsTrips: dict<int, gtfs.TripsEntry>
    @type gtfsStopTimes: dict<TripsEntry, list<gtfs.StopTimesEntry>>
    @type gtfsNodes: dict<int, list<path_engine.PathEnd>>
    @type vistaNetwork: graph.GraphLib
    @type stopSearchRadius: float
    @type excludeUpstream: boolean
    @type userName: str
    @type networkName: str
    @type startTime: datetime
    @type endTime: datetime
    @type widenBegin: bool
    @type widenEnd: bool
    @type excludeBegin: bool
    @type excludeEnd: bool
    @type outFile: file
    @return A mapping of stopID to points-on-links plus the start and end times adjusted for
            warm-up and cool-down (if widenBegin or widenEnd is True)
    @rtype (dict<int, graph.PointOnLink>, datetime, datetime)
    """
    _outHeader("public.bus_route_link", userName, networkName, outFile)
    print('"route","sequence","link","stop","dwelltime",', file = outFile)
    
    # Set up the output:
    ret = {}
    "@type ret: dict<int, graph.PointOnLink>"
        
    warmupStartTime = startTime
    cooldownEndTime = endTime

    # Initialize the path engine for use later:
    pathEngine = path_engine.PathEngine(stopSearchRadius, stopSearchRadius, stopSearchRadius, sys.float_info.max, sys.float_info.max,
                                        stopSearchRadius, DISTANCE_FACTOR, DRIFT_FACTOR, NON_PERP_PENALTY, sys.maxint, sys.maxint)
    pathEngine.limitClosestPoints = 8
    pathEngine.limitSimultaneousPaths = 6
    pathEngine.maxHops = 12
    pathEngine.logFile = None # Suppress the log outputs for the path engine; enough stuff will come from other sources.

    problemReportNodes = {}
    "@type problemReportNodes: dict<?, path_engine.PathEnd>"
    
    allResultTrees = {}
    "@type allResultTrees: dict<int, list<path_engine.PathEnd>>"
    allSubsets = {}
    "@type allSubsets: dict<int, graph.GraphLib>"
    allUsedTripIDs = []
    "@type allUsedTripIDs: list<int>"
    allStopsLookups = {}
    "@type allStopsLookups: dict<int, dict<int, gtfs.StopTimesEntry>>"
    
    print("INFO: ** INITIAL BUS STOP MATCHING STAGE **", file=sys.stderr)
    tripIDs = gtfsTrips.keys()
    tripIDs.sort()
    for tripID in tripIDs:
        if gtfsTrips[tripID].shapeEntries[0].shapeID not in gtfsNodes:
            # This happens if the incoming files contain a subset of all available topology.
            print("WARNING: Skipping route for trip %d because no points are available." % tripID, file=sys.stderr)
            continue
        
        # Step 1: Find the longest distance of contiguous valid links within the shape for each trip. And,
        # Step 2: Ignore routes that are entirely outside our valid time interval.
        print("INFO: -- Matching stops for trip %d --" % tripID, file=sys.stderr)
        ourGTFSNodes, longestStart = treeContiguous(gtfsNodes[gtfsTrips[tripID].shapeEntries[0].shapeID], vistaNetwork,
            gtfsStopTimes[gtfsTrips[tripID]], startTime, endTime)
        if ourGTFSNodes is None:
            print("INFO: Skipped because all stops fall outside of the valid time range, or there are no stops.", file=sys.stderr)
            continue                
            
        # Step 3: Build a new subset network with new links and nodes that represents the single-path
        # specified by the GTFS shape (for bus route):
        subset, outLinkList = buildSubset(ourGTFSNodes, vistaNetwork)
        
        # Step 4: Embellish the single-path subset with incoming and outgoing links at the beginning and ending areas
        # because we may need to move ambiguously matched bus stop locations around later. (We also find in GTFS sets that
        # occasionally GTFS shapes don't quite specify the respective bus route far enough).
        embellishSubset(subset, outLinkList, vistaNetwork)

        # Step 5: Match up stops to that contiguous list:
        print("INFO: Mapping stops to VISTA network...", file=sys.stderr)
        gtfsShapes, gtfsStopsLookup = prepareMapStops(ourGTFSNodes, gtfsStopTimes[gtfsTrips[tripID]])

        # Find a path through our prepared node map subset:
        resultTree = pathEngine.constructPath(gtfsShapes, subset)
        "@type resultTree: list<path_engine.PathEnd>"
        
        # So now we should have one tree entry per matched stop.

        # Store this for the next step, where we attempt to use the same bus stop location across all routes that use
        # that bus stop.
        allResultTrees[tripID] = resultTree
        allSubsets[tripID] = subset
        allUsedTripIDs.append(tripID)
        allStopsLookups[tripID] = gtfsStopsLookup
        del resultTree, subset, gtfsStopsLookup
            
    # Now figure out where stop locations differ among multiple routes that share the same stop.
    print("INFO: ** END INITIAL BUS STOP MATCHING STAGE **", file=sys.stderr)
    
    print("INFO: Resolving discrepancies in bus stop locations across all routes...", file=sys.stderr)    
    class StopRecord:
        """
        StopRecord is a container for storing all of the information about stops and links so that 
        the link that is used across all routes may be set to be the same.
        @ivar linkCounts: Stores a reference count for each link referring to this stop.
        @type linkCounts: dict<int, int>
        @ivar linkPresentCnt: Identifies for each link how many of the routes each is in.
        @type linkPresentCnt: dict<int, int>
        @ivar referents: Identifies for each trip the index in the respective treeEntry list addresses the stop.
        @type referents: dict<int, list<int>>
        @ivar refCount: The number of referents there are among all trips.
        @type refCount: int
        """
        def __init__(self):
            self.linkCounts = {}
            self.linkPresentCnt = {}
            self.referents = {}
            self.refCount = 0
    
    stopRecords = {}
    "@type stopRecords: dict<int, StopRecord>"
    for tripID in allUsedTripIDs:
        resultTree = allResultTrees[tripID]
        treeEntryIndex = 1
        gtfsStopsLookup = allStopsLookups[tripID]
        for treeEntry in resultTree[1:-1]:
            "@type treeEntry: path_engine.PathEnd"
            stopID = gtfsStopsLookup[treeEntry.shapeEntry.shapeSeq].stop.stopID
            if stopID not in stopRecords:
                stopRecords[stopID] = StopRecord()
            stopRecord = stopRecords[stopID]
            linkID = treeEntry.pointOnLink.link.uid
            
            # Count that this link is matched to this stop.
            if linkID not in stopRecord.linkCounts:
                stopRecord.linkCounts[linkID] = 0
                stopRecord.linkPresentCnt[linkID] = 0
            stopRecord.linkCounts[linkID] += 1
            
            # Identify where in the resultTree matched stops list this matched stop occurs.
            if tripID not in stopRecord.referents:
                stopRecord.referents[tripID] = []
            stopRecord.referents[tripID].append(treeEntryIndex)
            treeEntryIndex += 1
            
            # Increment the counter for the total number of references.
            stopRecord.refCount += 1
    del stopRecord, treeEntry
            
    # In preparation for the next step, capture a set of links that are in each subset:
    allSubsetLinks = {}
    "@type allSubsetLinks: dict<int, set(int)>"
    for tripID, subset in allSubsets.iteritems():
        subsetLinks = set()
        for subsetLink in subset.linkMap.itervalues():
            subsetLinks.add(subsetLink.uid)
        allSubsetLinks[tripID] = subsetLinks
    del subsetLinks, subset
    
    # Count how many times each link exists in each trip: 
    for stopRecord in stopRecords.itervalues():
        for tripID in stopRecord.referents.iterkeys():
            subsetLinks = allSubsetLinks[tripID]
            for linkID in stopRecord.linkPresentCnt.iterkeys():
                if linkID in subsetLinks:
                    stopRecord.linkPresentCnt[linkID] += 1
    del stopRecord, subsetLinks
                    
    # Vote on the most popular links:
    for stopID, stopRecord in stopRecords.iteritems():
        if len(stopRecord.linkCounts) <= 1:
            continue # All routes use the same link for the stop.
        sortList = []
        for linkID, linkPresentCount in stopRecord.linkPresentCnt.iteritems():
            sortList.append((linkPresentCount, stopRecord.linkCounts[linkID], linkID))
            
        # sortList will now have the most popular link at the bottom: 
        sortList = sorted(sortList)
        
        linkAssignmentCount = 0
        while len(sortList) > 0 and linkAssignmentCount < stopRecord.refCount:
            for tripID, treeEntryIndices in stopRecord.referents.iteritems():
                subset = allSubsets[tripID]
                "@type treeEntryIndices: list<int>"
                for treeEntryIndex in treeEntryIndices:
                    resultTree = allResultTrees[tripID]
                    
                    # Check to see if the link number needs to be reassigned and if the ideal link number is present:
                    if resultTree[treeEntryIndex].pointOnLink.link.uid != sortList[-1][2]:
                        if sortList[-1][2] in subsetLinks[tripID]:
                            # If we do need to reassign the link, invalidate the respective path match points. The refine() call
                            # will then reevaluate those points along the path.
                            resultTree[treeEntryIndex].restart = True
                            resultTree[treeEntryIndex].pointOnLink.link = subset.linkMap[sortList[-1][2]]
                            resultTree[treeEntryIndex].pointOnLink.dist = -1 
                            if treeEntryIndex < len(resultTree) - 1:
                                resultTree[treeEntryIndex + 1].restart = True
                            linkAssignmentCount += 1
                        # Else, don't increment the linkAssignmentCount because the proposed link isn't in the trip.
                    else:
                        # The link that's used is already the one that's most popular.
                        linkAssignmentCount += 1
            # Go to the next most popular link
            del sortList[-1]
            if len(sortList) > 0 and linkAssignmentCount < stopRecord.refCount:
                print("INFO: Stop %d cannot be applied to the same link across all routes that use that stop." % stopID, file=sys.stderr)
        del sortList
            
    print("INFO: ** BEGIN REFINING AND OUTPUT STAGE **", file=sys.stderr)
    pathEngine.setRefineParams(STOP_SEARCH_RADIUS, STOP_SEARCH_RADIUS)
    #pathEngine.logFile = None # Prevent the refine cycle from outputting status messages.
    for tripID in allUsedTripIDs:
        resultTree = allResultTrees[tripID]
        pathEngine.setForceLinks([result.pointOnLink.link for result in resultTree])
        
        print("INFO: -- Refining stops for trip %d --" % tripID, file=sys.stderr)
        resultTree = pathEngine.refinePath(resultTree, allSubsets[tripID]) 
        
        # Strip off the dummy ends:
        del resultTree[-1]
        del resultTree[0]
        if len(resultTree) > 0:
            resultTree[0].prevTreeNode = None
        
        # Deal with Problem Report:
        # TODO: The Problem Report will include all nodes on each path regardless of valid time interval;
        # However; we will not have gotten here if the trip was entirely outside of it. 
        if problemReport:
            problemReportNodes[gtfsTrips[tripID].shapeEntries[0].shapeID] = assembleProblemReport(resultTree, vistaNetwork)
                
        # Walk through our output link list and see when in time the resultTree entries occur. Keep those
        # that fall within our given time interval and entirely bail out on this trip if we are entirely
        # outside of the time range. We do this here because of the possibility that a route is shortened
        # because we are trying to match to, say, a subnetwork of a regional network. We had to have done
        # the steps above in order to know this.
        stopMatches = []
        "@type stopMatches: list<path_engine.PathEnd>"
        rejectFlag = False
        for treeEntry in resultTree:
            "@type treeEntry: path_engine.PathEnd"
            gtfsStopTime = gtfsStopsLookup[treeEntry.shapeEntry.shapeSeq]
            if excludeBegin and gtfsStopTime.arrivalTime < startTime or excludeEnd and gtfsStopTime.arrivalTime > endTime:
                # Throw away this entire route because it is excluded and part of it falls outside:
                print("INFO: Excluded because activity happens outside of the valid time range.", file=sys.stderr)
                del stopMatches[:]
                rejectFlag = True
                break
            elif (widenBegin or gtfsStopTime.arrivalTime >= startTime) and (widenEnd or gtfsStopTime.arrivalTime <= endTime):
                stopMatches.append(treeEntry)
                
        # Then, output the results if we had not been rejected:
        foundStopSet = set()
        if not rejectFlag:
            if len(gtfsStopsLookup) > 0 and len(stopMatches) == 0:
                # TODO: Because of a continue further above, this should never happen. 
                print("INFO: No stops fall within the valid time range.")
            outSeqCtr = longestStart
            minTime = warmupStartTime
            maxTime = cooldownEndTime
            foundValidStop = False
            stopMatchIndex = 0
            for treeEntry in resultTree:
                # First, output the links leading up to this stop:
                if len(treeEntry.routeInfo) - 1 > 0:
                    for routeInfoElem in treeEntry.routeInfo[0:-1]:
                        print('"%d","%d","%d",,,' % (tripID, outSeqCtr, routeInfoElem.id), file=outFile)
                        outSeqCtr += 1
                    
                if stopMatchIndex < len(stopMatches) and treeEntry == stopMatches[stopMatchIndex]:
                    foundStopSet.add(treeEntry.shapeEntry.shapeSeq) # Check off this stop sequence.
                    foundValidStop = True
                    stopID = gtfsStopsLookup[treeEntry.shapeEntry.shapeSeq].stop.stopID
                    print('"%d","%d","%d","%d","%d",' % (tripID, outSeqCtr, treeEntry.pointOnLink.link.id,
                        stopID, DWELLTIME_DEFAULT), file=outFile)
                    if stopID in ret and ret[stopID].link.id != treeEntry.pointOnLink.link.id:
                        print("WARNING: stopID %d is attempted to be assigned to linkID %d, but it had already been assigned to linkID %d." \
                            % (stopID, treeEntry.pointOnLink.link.id, ret[stopID].link.id), file=sys.stderr)
                        # TODO: This is a tricky problem. This means that among multiple bus routes, the same stop had been
                        # found to best fit two different links. I don't exactly know the best way to resolve this, other
                        # than (for NMC analyses) to create a "fake" stop that's tied with the new link. 
                    else:
                        ret[stopID] = treeEntry.pointOnLink
                        
                    # Check on the minimum/maximum time range:
                    gtfsStopTime = gtfsStopsLookup[treeEntry.shapeEntry.shapeSeq]
                    minTime = min(gtfsStopTime.arrivalTime, minTime)
                    maxTime = max(gtfsStopTime.arrivalTime, maxTime)
                    stopMatchIndex += 1
                else:
                    # The linkID has nothing to do with any points in consideration.  Report it without a stop:
                    if foundValidStop or not excludeUpstream:
                        print('"%d","%d","%d",,,' % (tripID, outSeqCtr, treeEntry.pointOnLink.link.id), file=outFile)
                outSeqCtr += 1
                # TODO: For start time estimation (as reported in the public.bus_frequency.csv output), it may be
                # ideal to keep track of linear distance traveled before the first valid stop.
                
            # Widen out the valid interval if needed:
            warmupStartTime = min(minTime, warmupStartTime)
            cooldownEndTime = max(maxTime, cooldownEndTime)

        # Are there any stops left over?  If so, report them to say that they aren't in the output file.
        stopTimes = gtfsStopTimes[gtfsTrips[tripID]]
        "@type stopTimes: list<gtfs.StopTimesEntry>"
        startGap = -1
        endGap = -1
        for gtfsStopTime in stopTimes:
            "@type gtfsStopTime: gtfs.StopTimesEntry"
            flag = False
            if gtfsStopTime.stopSeq not in foundStopSet:
                # This stop is unaccounted for:
                if startGap < 0:
                    startGap = gtfsStopTime.stopSeq
                endGap = gtfsStopTime.stopSeq
                
                # Old message is very annoying, especially if the underlying topology is a subset of shapefile
                # geographic area and there's a ton of them. That's why there is the new range message as shown below.
                # print("WARNING: Trip tripID %d, stopID %d stop seq. %d will not be in the bus_route_link file." % (tripID,
                #    gtfsStopTime.stop.stopID, gtfsStopTime.stopSeq), file=sys.stderr)
                
                if problemReport:
                    revisedNodeList = problemReportNodes[gtfsTrips[tripID].shapeEntries[0].shapeID]  
                    if gtfsStopTime.stopSeq not in revisedNodeList:
                        # Make a dummy "error" node for reporting.
                        newShape = gtfs.ShapesEntry(gtfsTrips[tripID].shapeEntries[0].shapeID,
                            gtfsStopTime.stopSeq, gtfsStopTime.stop.gpsLat,gtfsStopTime.stop.gpsLng, False)
                        newPointOnLink = graph.PointOnLink(None, 0)
                        newPointOnLink.pointX = gtfsStopTime.stop.pointX
                        newPointOnLink.pointY = gtfsStopTime.stop.pointY
                        newNode = path_engine.PathEnd(newShape, newPointOnLink)
                        newNode.restart = True
                        revisedNodeList[gtfsStopTime.stopSeq] = newNode
            else:
                flag = True
            if (flag or gtfsStopTime.stopSeq == stopTimes[-1].stopSeq) and startGap >= 0:
                subStr = "Seqs. %d-%d" % (startGap, endGap) if startGap != endGap else "Seq. %d" % startGap
                print("WARNING: Trip ID %d, Stop %s will not be in the bus_route_link file." % (tripID, subStr),
                    file=sys.stderr)
                startGap = -1

    # Deal with Problem Report:
    if problemReport:
        print("INFO: Output problem report CSV...", file=sys.stderr)
        problemReportNodesOut = {}
        for shapeID in problemReportNodes:
            seqs = problemReportNodes[shapeID].keys()
            seqs.sort()
            ourTgtList = []
            for seq in seqs:
                ourTgtList.append(problemReportNodes[shapeID][seq])
            problemReportNodesOut[shapeID] = ourTgtList                
        problem_report.problemReport(problemReportNodesOut, vistaNetwork)
    
    print("INFO: ** END REFINING AND OUTPUT STAGE **", file=sys.stderr)
    return ret, warmupStartTime, cooldownEndTime 

def dumpBusStops(gtfsStops, stopLinkMap, userName, networkName, outFile = sys.stdout):
    """
    dumpBusRouteStops dumps out a public.bus_route_link.csv file contents.
    @type gtfsStops: dict<int, StopsEntry>
    @type stopLinkMap: dict<int, graph.PointOnLink>
    @type userName: str
    @type networkName: str
    @type outFile: file
    """
    _outHeader("public.bus_stop", userName, networkName, outFile)
    print('"id","link","name","location",', file = outFile)
    
    # Iterate through the stopLinkMap:
    for stopID in stopLinkMap:
        "@type stopID: int"
        pointOnLink = stopLinkMap[stopID]
        "@type pointOnLink: graph.PointOnLink"
        print('"%d","%d","%s","%d"' % (stopID, pointOnLink.link.id, gtfsStops[stopID].stopName, int(pointOnLink.dist)), file = outFile) 

def main(argv):
    global problemReport
    excludeUpstream = False
    
    # Initialize from command-line parameters:
    if len(argv) < 7:
        syntax(1)
    dbServer = argv[1]
    networkName = argv[2]
    userName = argv[3]
    password = argv[4]
    shapePath = argv[5]
    pathMatchFilename = argv[6]
    endTimeInt = 86400
    refTime = None
    widenBegin = False
    widenEnd = False
    excludeBegin = False
    excludeEnd = False
    
    restrictService = set()
    "@type restrictService: set<string>"

    if len(argv) > 6:
        i = 7
        while i < len(argv):
            if argv[i] == "-t" and i < len(argv) - 1:
                refTime = datetime.strptime(argv[i + 1], '%H:%M:%S')
                i += 1
            elif argv[i] == "-e" and i < len(argv) - 1:
                endTimeInt = int(argv[i + 1])
                i += 1
            elif argv[i] == "-c" and i < len(argv) - 1:
                restrictService.add(argv[i + 1])
                i += 1
            elif argv[i] == "-u":
                excludeUpstream = True
            elif argv[i] == "-w":
                widenBegin = True
                widenEnd = True
            elif argv[i] == "-wb":
                widenBegin = True
            elif argv[i] == "-we":
                widenEnd = True
            elif argv[i] == "-x":
                excludeBegin = True
                excludeEnd = True
            elif argv[i] == "-xb":
                excludeBegin = True
            elif argv[i] == "-xe":
                excludeEnd = True
            elif argv[i] == "-p":
                problemReport = True
            i += 1
    
    if refTime is None:
        print("ERROR: No reference time is specified. You must use the -t parameter.", file=sys.stderr)
        syntax(1)
    endTime = refTime + timedelta(seconds = endTimeInt)
    
    if widenBegin and excludeBegin:
        print("ERROR: Widening (-w or -wb) and exclusion (-x or -xb) cannot be used together.")
        syntax(1)    
    if widenEnd and excludeEnd:
        print("ERROR: Widening (-w or -we) and exclusion (-x or -xe) cannot be used together.")
        syntax(1)
    
    # Restore the stuff that was built with path_match:
    (vistaGraph, gtfsShapes, gtfsNodes, unusedShapeIDs) = restorePathMatch(dbServer, networkName, userName,
        password, shapePath, pathMatchFilename)
    
    # Read in the routes information:
    print("INFO: Read GTFS routesfile...", file=sys.stderr)
    gtfsRoutes = gtfs.fillRoutes(shapePath)
    "@type gtfsRoutes: dict<int, RoutesEntry>"
    
    # Read in the stops information:
    print("INFO: Read GTFS stopsfile...", file=sys.stderr)
    gtfsStops = gtfs.fillStops(shapePath, vistaGraph.gps)
    "@type gtfsStops: dict<int, StopsEntry>"
    
    # Read in the trips information:
    print("INFO: Read GTFS tripsfile...", file=sys.stderr)
    (gtfsTrips, unusedTripIDs) = gtfs.fillTrips(shapePath, gtfsShapes, gtfsRoutes, unusedShapeIDs, restrictService)
    "@type gtfsTrips: dict<int, TripsEntry>"
    "@type unusedTripIDs: set<int>"
        
    # Read stop times information:
    print("INFO: Read GTFS stop times...", file=sys.stderr)
    gtfsStopTimes = gtfs.fillStopTimes(shapePath, gtfsTrips, gtfsStops, unusedTripIDs)
    "@type gtfsStopTimes: dict<TripsEntry, list<StopTimesEntry>>"
        
    # Output the routes_link file:
    print("INFO: Dumping public.bus_route_link.csv...", file=sys.stderr)
    with open("public.bus_route_link.csv", 'w') as outFile:
        (stopLinkMap, newStartTime, newEndTime) = dumpBusRouteLinks(gtfsTrips, gtfsStopTimes, gtfsNodes, vistaGraph,
            STOP_SEARCH_RADIUS, excludeUpstream, userName, networkName, refTime, endTime, widenBegin, widenEnd,
            excludeBegin, excludeEnd, outFile)
        "@type stopLinkMap: dict<int, graph.PointOnLink>"
    
    # Filter only to bus stops and stop times that are used in the routes_link output:
    gtfsStopsFilterList = [gtfsStopID for gtfsStopID in gtfsStops if gtfsStopID not in stopLinkMap]
    for gtfsStopID in gtfsStopsFilterList:
        del gtfsStops[gtfsStopID]
    del gtfsStopsFilterList
    
    # Then, output the output the stop file:
    print("INFO: Dumping public.bus_stop.csv...", file=sys.stderr)
    with open("public.bus_stop.csv", 'w') as outFile:
        dumpBusStops(gtfsStops, stopLinkMap, userName, networkName, outFile)
        
    print("INFO: Dumping public.bus_frequency.csv...", file=sys.stderr)
    validTrips = {}
    "@type validTrips: dict<int, gtfs.TripsEntry>"
    with open("public.bus_frequency.csv", 'w') as outFile:
        _outHeader("public.bus_frequency", userName, networkName, outFile)
        print("\"route\",\"period\",\"frequency\",\"offsettime\",\"preemption\"", file = outFile)
        
        # Okay, here we iterate through stops until we get to the first defined one. That will
        # then affect the offsettime. (This is needed because of the idea that we want to start
        # a bus in the simulation wrt the topology that supports it, skipping those stops that
        # may fall outside the topology.)
        totalCycle = int((newEndTime - newStartTime).total_seconds()) 
        tripIDs = gtfsTrips.keys()
        tripIDs.sort()
        for tripID in tripIDs:
            stopsEntries = gtfsStopTimes[gtfsTrips[tripID]]
            for gtfsStopTime in stopsEntries:
                if gtfsStopTime.stop.stopID in gtfsStops:
                    # Here is a first valid entry! Use this offset value.
                    
                    # TODO: This could be inaccurate because the offset is that of the first
                    # valid stop time encountered in the underlying topology, not approximated
                    # to the first valid link encountered. While this isn't a big deal for an
                    # area with a high stop density, it could be a problem for limited-stop
                    # service where there happens to be a low density around where the bus
                    # first appears in the underlying topology.
                    stopTime = gtfsStopTime.arrivalTime
                    
                    # Adjust for cases where we need to add a day.
                    if stopTime < newStartTime: # Assume that we're working just within a day.
                        stopTime += timedelta(days = int((newStartTime - stopTime).total_seconds()) / 86400 + 1)
                    print("%d,1,%d,%d,0" % (tripID, totalCycle, int((stopTime - newStartTime).total_seconds())),
                        file = outFile)
                    validTrips[tripID] = gtfsTrips[tripID] # Record as valid.
                    break
                    
                # A byproduct of this scheme is that no bus_frequency entry will appear for
                # routes that don't have stops in the underlying topology.

    # Output the routes file:
    print("INFO: Dumping public.bus_route.csv...", file=sys.stderr)
    with open("public.bus_route.csv", 'w') as outFile:
        dumpBusRoutes(validTrips, userName, networkName, outFile)

    # Finally, define one period that spans the whole working time, which all of the individually
    # defined routes (again, one route per trip) will operate in.
    print("INFO: Dumping public.bus_period.csv...", file=sys.stderr)
    with open("public.bus_period.csv", 'w') as outFile:
        _outHeader("public.bus_period", userName, networkName, outFile)
        print("\"id\",\"starttime\",\"endtime\"", file = outFile)
        # The start time printed here is relative to the reference time.
        print("1,0,%d" % endTimeInt, file = outFile)
        
    if widenBegin or widenEnd:
        # Report the implicit adjustment in times because of warmup or cooldown:
        startTimeDiff = refTime - newStartTime
        endTimeDiff = newEndTime - endTime
        print("INFO: Widening requires start %d sec. earlier and duration %d sec. longer." % (startTimeDiff.total_seconds(),
            endTimeDiff.total_seconds() + startTimeDiff.total_seconds()), file=sys.stderr)
        totalTimeDiff = newEndTime - newStartTime
        print("INFO: New time reference is %s, duration %d sec." % (newStartTime.strftime("%H:%M:%S"), totalTimeDiff.total_seconds()),
            file=sys.stderr)

    print("INFO: Done.", file=sys.stderr)

# Boostrap:
if __name__ == '__main__':
    main(sys.argv)
