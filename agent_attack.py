# build base sub agent
import sys
import random
import math
import time
import os.path

import numpy as np
import pandas as pd

from pysc2.lib import actions

from utils import BaseAgent
from utils import EmptySharedData

from utils import TerranUnit
from utils import SC2_Params
from utils import SC2_Actions

#decision makers
from algo_decisionMaker import BaseDecisionMaker

from agent_battle_mngr import BattleMngr
from agent_battle_mngr import SharedDataBattle

# params
from utils import CountSelectedLocationMat
from utils import SwapPnt
from utils import DistForCmp
from utils import CenterPoints
from utils import SelectUnitValidPoints
from utils import FindMiddle

AGENT_DIR = "AttackAgent/"
AGENT_NAME = "attack_agent"

SUB_AGENT_ID_BATTLEMNGR = 0
SUBAGENTS_NAMES = {}
SUBAGENTS_NAMES[SUB_AGENT_ID_BATTLEMNGR] = "BattleMngr"

CONTROL_GROUP_ID_ATTACK = [5]
ATTACK_STARTED_RANGE_ENEMY = 10

GRID_SIZE = 2

ACTIONS_START_IDX_ATTACK = 0
ACTIONS_END_IDX_ATTACK = ACTIONS_START_IDX_ATTACK + GRID_SIZE * GRID_SIZE
NUM_ACTIONS = ACTIONS_END_IDX_ATTACK


class SharedDataAttack(SharedDataBattle):
    def __init__(self):
        super(SharedDataAttack, self).__init__()
        self.enemyMat = np.zeros((SC2_Params.MINIMAP_SIZE, SC2_Params.MINIMAP_SIZE), int)
        self.armyInAttack = {}

class AttackAgent(BaseAgent):
    def __init__(self, sharedData, configDict, decisionMaker, isMultiThreaded, playList, trainList, testList, dmCopy=None): 
        super(AttackAgent, self).__init__()  

        self.sharedData = sharedData
        
        self.playAgent = (AGENT_NAME in playList) | ("inherit" in playList)
        if self.playAgent:
            saPlayList = ["inherit"]
        else:
            saPlayList = playList

        if decisionMaker != None:
            self.decisionMaker = decisionMaker
        else:
            self.decisionMaker = BaseDecisionMaker(AGENT_NAME)

        self.subAgents = {}
        for key, name in SUBAGENTS_NAMES.items():
            saClass = eval(name)
            saDM = self.decisionMaker.GetSubAgentDecisionMaker(key)
            self.subAgents[key] = saClass(sharedData=sharedData, configDict=configDict, decisionMaker=saDM, isMultiThreaded=isMultiThreaded, playList=saPlayList, 
                                            trainList=trainList, testList=testList, dmCopy=dmCopy)
            self.decisionMaker.SetSubAgentDecisionMaker(key, self.subAgents[key].GetDecisionMaker())

        if not self.playAgent:
            self.subAgentPlay = self.FindActingHeirarchi()
            self.activeSubAgents = [self.subAgentPlay]
        else: 
            self.activeSubAgents = list(SUBAGENTS_NAMES.keys())
            
        self.SetGridSize(GRID_SIZE)

    def GetDecisionMaker(self):
        return self.decisionMaker

    def GetAgentByName(self, name):
        if AGENT_NAME == name:
            return self
        
        for sa in self.subAgents.values():
            ret = sa.GetAgentByName(name)
            if ret != None:
                return ret
            
        return None
       
    def EndRun(self, reward, score, stepNum):     
        for sa in self.activeSubAgents:
            if reward > 0:
                reward = 1.0
            else:
                reward = -1.0
                
            self.subAgents[sa].Learn(reward, True)
            self.subAgents[sa].EndRun(reward, score, stepNum) 


    def UpdateEnemyMat(self, obs):
        miniMapEnemy = obs.observation['feature_minimap'][SC2_Params.PLAYER_RELATIVE_MINIMAP] == SC2_Params.PLAYER_HOSTILE

        for y in range(SC2_Params.MINIMAP_SIZE):
            for x in range(SC2_Params.MINIMAP_SIZE):                
                self.sharedData.enemyMat[y,x] = miniMapEnemy[y][x]

    def FindActingHeirarchi(self):
        if self.playAgent:
            return 1
        
        for key, sa in self.subAgents.items():
            if sa.FindActingHeirarchi() >= 0:
                return key

        return -1

    def SetGridSize(self, gridSize):
        self.gridSize = gridSize
        
        self.action2Start = {}
        self.action2End = {}

        for y in range(self.gridSize):
            p_y = (SC2_Params.MINIMAP_SIZE * y /  gridSize)
            pEnd_y = (SC2_Params.MINIMAP_SIZE * (y + 1) /  gridSize)
            for x in range(self.gridSize):
                idx = x + y * gridSize
                p_x = (SC2_Params.MINIMAP_SIZE * x /  gridSize)
                pEnd_x = (SC2_Params.MINIMAP_SIZE * (x + 1) /  gridSize)
                
                self.action2Start[ACTIONS_START_IDX_ATTACK + idx] = [int(p_y), int(p_x)]
                self.action2End[ACTIONS_START_IDX_ATTACK + idx] = [int(pEnd_y), int(pEnd_x)]

    def FirstStep(self, obs):
        super(AttackAgent, self).FirstStep()

        if self.playAgent:
            self.destinationCoord = [-1,-1]
            self.attackPreformAction = False
        else:
            self.attackPreformAction = True

        for sa in SUBAGENTS_NAMES.keys():
            self.subAgents[sa].FirstStep(obs) 

    def Action2Str(self, a, onlyAgent=False):
        if self.attackPreformAction:
            return self.subAgents[SUB_AGENT_ID_BATTLEMNGR].Action2Str()
        else: 
            return "GoTo_" + str(a)

    def IsDoNothingAction(self, a):
        return False
    
    def ChooseAction(self):
        if not self.playAgent:
            if self.subAgentPlay >= 0:
                return self.subAgents[self.subAgentPlay].ChooseAction()
        
        return 0
        
    def Action2SC2Action(self, obs, a, moveNum):
        if self.playAgent:
            if moveNum == 0:
                if SC2_Actions.SELECT_ARMY in obs.observation['available_actions']:
                    return actions.FunctionCall(SC2_Actions.SELECT_ARMY, [SC2_Params.NOT_QUEUED]), False

            elif moveNum == 1:

                self.sharedData.armyInAttack = self.ArmySelected(obs)
                CountSelectedLocationMat(obs, self.sharedData.superGridSize, self.sharedData.selfArmyMat)
                if len(self.sharedData.armyInAttack) > 0:
                    coordBattle = self.InBattle(obs)
                    if self.sharedData.inBattle:
                        self.attackPreformAction = True
                        self.moveNum = 0
                        return actions.FunctionCall(SC2_Actions.MOVE_CAMERA, [SwapPnt(coordBattle)]), False

                    elif SC2_Actions.ATTACK_MINIMAP in obs.observation['available_actions']:     
                        coord = self.AttackCoord(a, obs)
                        return actions.FunctionCall(SC2_Actions.ATTACK_MINIMAP, [SC2_Params.NOT_QUEUED, SwapPnt(coord)]), True
                    

            elif moveNum >= 2:
                if self.sharedData.inBattle:
                    if self.attackPreformAction:
                        sc2Action, terminal = self.subAgents[SUB_AGENT_ID_BATTLEMNGR].Action2SC2Action(obs, self.moveNum)
                        self.moveNum += 1
                        self.attackPreformAction = not terminal
                        return sc2Action, False
                    else:
                        return actions.FunctionCall(SC2_Actions.MOVE_CAMERA, [SwapPnt(self.sharedData.commandCenterLoc[0])]), True
        else:
            return self.subAgents[SUB_AGENT_ID_BATTLEMNGR].Action2SC2Action(obs, moveNum)
                    
        
        return SC2_Actions.DO_NOTHING_SC2_ACTION, True

    def ArmySelected(self, obs):
        unitCount = {}
        
        unitStatus = obs.observation['multi_select']
        
        if len(unitStatus) == 0:
            unitStatus = obs.observation['single_select']
            if len(unitStatus) == 0:
                return unitCount
        
        
        # count army
        for unit in unitStatus:
            uType = unit[SC2_Params.UNIT_TYPE_IDX]
            
            if uType in unitCount:
                unitCount[uType][0] += 1
            else:
                unitCount[uType] = [1]

        return unitCount

    def AttackCoord(self, action, obs):
        coordStart = self.action2Start[action]
        coordEnd = self.action2End[action]
        coord2Go = np.add(coordStart, coordEnd) / 2
        
        enemyMat = obs.observation["feature_minimap"][SC2_Params.PLAYER_RELATIVE_MINIMAP] == SC2_Params.PLAYER_HOSTILE
        if enemyMat.any():
            miniMapCoordRange = np.zeros((SC2_Params.MINIMAP_SIZE, SC2_Params.MINIMAP_SIZE), bool)
            miniMapCoordRange[coordStart[SC2_Params.Y_IDX]:coordEnd[SC2_Params.Y_IDX], coordStart[SC2_Params.X_IDX]:coordEnd[SC2_Params.X_IDX]] = True
            enemy_y, enemy_x = (enemyMat & miniMapCoordRange).nonzero()
            minDist = 100000

            for i in range(len(enemy_y)):
                diffY = enemy_y[i] - coordStart[0]
                diffX = enemy_x[i] - coordStart[1]
                dist = diffY * diffY + diffX * diffX
                if dist < minDist:
                    minDist = dist
                    coord2Go = [enemy_y[i], enemy_x[i]]

        return coord2Go

    def InBattle(self, obs):
        s_y, s_x = obs.observation['feature_minimap'][SC2_Params.SELECTED_IN_MINIMAP].nonzero()
        e_y, e_x = (obs.observation['feature_minimap'][SC2_Params.PLAYER_RELATIVE_MINIMAP] == SC2_Params.PLAYER_HOSTILE).nonzero()

        
        minDist = 1000
        minIdx = -1
        self.sharedData.inBattle = False

        for s in range(len(s_y)):
            for e in range(len(e_y)):
                diffY = s_y[s] - e_y[e]
                diffX = s_x[s] - e_x[e]
                dist = diffY * diffY + diffX * diffX
                if dist < minDist:
                    minDist = dist
                    minIdx = s

        dist2Attack = ATTACK_STARTED_RANGE_ENEMY * ATTACK_STARTED_RANGE_ENEMY
        if minDist < dist2Attack:
            self.sharedData.inBattle = True
            return [s_y[minIdx] , s_x[minIdx]]   
        
        return [-1,-1]

    def GetSelectedUnitsLocation(self, obs):
        armyLoc = [0] * (GRID_SIZE * GRID_SIZE)

        army_y, army_x = obs.observation['feature_minimap'][SC2_Params.SELECTED_IN_MINIMAP].nonzero()
        for i in range(len(army_y)):
            idx = self.Scale2GridSize(army_y[i], army_x[i], SC2_Params.MINIMAP_SIZE)
            armyLoc[idx] += 1
        
        return armyLoc
    
    def Scale2GridSize(self,y,x, oldGridSize):
        xScaled = int((x / oldGridSize) * GRID_SIZE)
        yScaled = int((y / oldGridSize) * GRID_SIZE)

        return xScaled + yScaled * GRID_SIZE
        
