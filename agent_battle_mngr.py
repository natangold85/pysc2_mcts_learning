# build base sub agent
import sys
import random
import math
import time
import os.path
import datetime

import numpy as np
import pandas as pd
import tensorflow as tf

from pysc2.lib import actions

from utils import BaseAgent

#sub-agents
from agent_base_attack import BaseAttack
from agent_army_attack import ArmyAttack

from utils import TerranUnit
from utils import SC2_Params
from utils import SC2_Actions

#decision makers
from utils_decisionMaker import LearnWithReplayMngr
from utils_decisionMaker import UserPlay
from utils_decisionMaker import BaseDecisionMaker


from utils_results import ResultFile
from utils_results import PlotMngr

# params
from utils_dqn import DQN_PARAMS
from utils_dqn import DQN_EMBEDDING_PARAMS
from utils_qtable import QTableParams
from utils_qtable import QTableParamsExplorationDecay

from utils import EmptySharedData

from utils import SwapPnt
from utils import DistForCmp
from utils import CenterPoints

# possible types of play
AGENT_DIR = "BattleMngr/"
if not os.path.isdir("./" + AGENT_DIR):
    os.makedirs("./" + AGENT_DIR)

AGENT_NAME = "battle_mngr"

QTABLE = 'q'
DQN = 'dqn'
DQN_EMBEDDING_LOCATIONS = 'dqn_Embedding' 
NAIVE_DECISION = 'naive'

USER_PLAY = 'play'

ALL_TYPES = set([USER_PLAY, QTABLE, DQN, DQN_EMBEDDING_LOCATIONS, NAIVE_DECISION])


GRID_SIZE = 5


ACTION_DO_NOTHING = 0
ACTION_ARMY_BATTLE = 1
ACTION_BASE_BATTLE = 2
NUM_ACTIONS = 3

ACTION2STR = {}
ACTION2STR[ACTION_DO_NOTHING] = "Do_Nothing"
ACTION2STR[ACTION_ARMY_BATTLE] = "Army_Battle"
ACTION2STR[ACTION_BASE_BATTLE] = "Base_Battle"

class STATE:
    START_SELF_MAT = 0
    END_SELF_MAT = GRID_SIZE * GRID_SIZE
    
    START_ENEMY_MAT = END_SELF_MAT
    END_ENEMY_MAT = START_ENEMY_MAT + GRID_SIZE * GRID_SIZE
    
    START_BUILDING_MAT = END_ENEMY_MAT
    END_BUILDING_MAT = START_BUILDING_MAT + GRID_SIZE * GRID_SIZE

    TIME_LINE_IDX = END_BUILDING_MAT

    SIZE = TIME_LINE_IDX + 1

    TIME_LINE_BUCKETING = 25

SUBAGENTS_NAMES = {}
SUBAGENTS_NAMES[ACTION_DO_NOTHING] = "BaseAgent"
SUBAGENTS_NAMES[ACTION_ARMY_BATTLE] = "ArmyAttack"
SUBAGENTS_NAMES[ACTION_BASE_BATTLE] = "BaseAttack"

SUBAGENTS_ARGS = {}
SUBAGENTS_ARGS[ACTION_DO_NOTHING] = "naive"
SUBAGENTS_ARGS[ACTION_ARMY_BATTLE] = "dqn"
SUBAGENTS_ARGS[ACTION_BASE_BATTLE] = "naive"

def NNFunc_2Layers(x, numActions, scope):
    with tf.variable_scope(scope):
        # Fully connected layers
        fc1 = tf.contrib.layers.fully_connected(x, 256)
        fc2 = tf.contrib.layers.fully_connected(fc1, 256)
        output = tf.contrib.layers.fully_connected(fc2, numActions, activation_fn = tf.nn.sigmoid) * 2 - 1
    return output


NUM_UNIT_SCREEN_PIXELS = 0

for key,value in TerranUnit.UNIT_SPEC.items():
    if value.name == "marine":
        NUM_UNIT_SCREEN_PIXELS = value.numScreenPixels


# data for run type
TYPE = "type"
DECISION_MAKER_NAME = "dm_name"
HISTORY = "hist"
RESULTS = "results"
PARAMS = 'params'
DIRECTORY = 'directory'

# table names
RUN_TYPES = {}


RUN_TYPES[QTABLE] = {}
RUN_TYPES[QTABLE][TYPE] = "QLearningTable"
RUN_TYPES[QTABLE][DIRECTORY] = "battleMngr_qtable"
RUN_TYPES[QTABLE][PARAMS] = QTableParamsExplorationDecay(STATE.SIZE, NUM_ACTIONS)
RUN_TYPES[QTABLE][DECISION_MAKER_NAME] = "battleMngr_q_qtable"
RUN_TYPES[QTABLE][HISTORY] = "battleMngr_q_replayHistory"
RUN_TYPES[QTABLE][RESULTS] = "battleMngr_q_result"

RUN_TYPES[DQN] = {}
RUN_TYPES[DQN][TYPE] = "DQN_WithTarget"
RUN_TYPES[DQN][DIRECTORY] = "battleMngr_dqn"
RUN_TYPES[DQN][PARAMS] = DQN_PARAMS(STATE.SIZE, NUM_ACTIONS)
RUN_TYPES[DQN][DECISION_MAKER_NAME] = "battleMngr_dqn_DQN"
RUN_TYPES[DQN][HISTORY] = "battleMngr_dqn_replayHistory"
RUN_TYPES[DQN][RESULTS] = "battleMngr_dqn_result"

RUN_TYPES[DQN_EMBEDDING_LOCATIONS] = {}
RUN_TYPES[DQN_EMBEDDING_LOCATIONS][TYPE] = "DQN_WithTarget"
RUN_TYPES[DQN][DIRECTORY] = "battleMngr_dqn_Embedding"
RUN_TYPES[DQN_EMBEDDING_LOCATIONS][PARAMS] = DQN_EMBEDDING_PARAMS(STATE.SIZE, STATE.END_BUILDING_MAT, NUM_ACTIONS)
RUN_TYPES[DQN_EMBEDDING_LOCATIONS][DECISION_MAKER_NAME] = "battleMngr_dqn_Embedding_DQN"
RUN_TYPES[DQN_EMBEDDING_LOCATIONS][HISTORY] = "battleMngr_dqn_Embedding_replayHistory"
RUN_TYPES[DQN_EMBEDDING_LOCATIONS][RESULTS] = "battleMngr_dqn_Embedding_result"


RUN_TYPES[USER_PLAY] = {}
RUN_TYPES[USER_PLAY][TYPE] = "play"

RUN_TYPES[NAIVE_DECISION] = {}
RUN_TYPES[NAIVE_DECISION][RESULTS] = "battleMngr_naive_result"
RUN_TYPES[NAIVE_DECISION][TYPE] = "naive"


class SharedDataBattle(EmptySharedData):
    def __init__(self):
        super(SharedDataBattle, self).__init__()


class NaiveDecisionMakerBattleMngr(BaseDecisionMaker):
    def __init__(self, gridSize, resultFName):
        super(NaiveDecisionMakerBattleMngr, self).__init__()
        self.resultsFile = ResultFile(resultFName)
        
        self.gridSize = gridSize
        self.startEnemyMat = gridSize * gridSize
        self.startBuildingMat = 2 * gridSize * gridSize
        self.endBuildingMat = 3 * gridSize * gridSize

        self.numActions = 3

    def choose_action(self, observation):
        if (observation[self.startEnemyMat:self.startBuildingMat] > 0).any():
            return ACTION_ARMY_BATTLE
        elif (observation[self.startBuildingMat:self.endBuildingMat] > 0).any():
            return ACTION_BASE_BATTLE
        else:
            return ACTION_DO_NOTHING

    def learn(self, s, a, r, s_, terminal = False):
        return None

    def ActionValuesVec(self, state):
        vals = np.zeros(self.numActions,dtype = float)
        vals[self.choose_action(state)] = 1.0

        return vals

    def end_run(self, r, score = 0 ,steps = 0):
        self.resultsFile.end_run(r,score,steps, True)
        return True

    def ExploreProb(self):
        return 0


class BattleMngr(BaseAgent):
    def __init__(self, runArg = None, decisionMaker = None, isMultiThreaded = False, playList = None, trainList = None):        
        super(BattleMngr, self).__init__()
        self.playAgent = (AGENT_NAME in playList) | ("inherit" in playList)
        if self.playAgent:
            saPlayList = ["inherit"]
        else:
            saPlayList = playList

        self.trainAgent = AGENT_NAME in trainList

        self.illigalmoveSolveInModel = True

        if decisionMaker != None:
            self.decisionMaker = decisionMaker
        else:
            self.decisionMaker = self.CreateDecisionMaker(runArg, isMultiThreaded)

        self.subAgents = {}
        for key, name in SUBAGENTS_NAMES.items():
            saClass = eval(name)
            saDM = self.decisionMaker.GetSubAgentDecisionMaker(key)
            
            saArg = SUBAGENTS_ARGS[key]
            if saArg == "inherit":
                saArg = runArg

            self.subAgents[key] = saClass(saArg, saDM, isMultiThreaded, saPlayList, trainList)
            self.decisionMaker.SetSubAgentDecisionMaker(key, self.subAgents[key].GetDecisionMaker())

        if not self.playAgent:
            self.subAgentPlay = self.FindActingHeirarchi()
            self.activeSubAgents = [self.subAgentPlay]
        else: 
            self.activeSubAgents = list(range(NUM_ACTIONS))


        self.current_action = None
        self.armyExist = True
        self.buildingsExist = True
        # state and actions:

        self.state_startSelfMat = 0
        self.state_startEnemyMat = GRID_SIZE * GRID_SIZE
        self.state_startBuildingMat = 2 * GRID_SIZE * GRID_SIZE
        self.state_timeLineIdx = 3 * GRID_SIZE * GRID_SIZE

        self.state_size = 3 * GRID_SIZE * GRID_SIZE + 1

        self.terminalState = np.zeros(self.state_size, dtype=np.int, order='C')
        
        self.BuildingValues = {}
        for spec in TerranUnit.BUILDING_SPEC.values():
            self.BuildingValues[spec.name] = 1


    def CreateDecisionMaker(self, runArg, isMultiThreaded):
        if runArg == None:
            runTypeArg = list(ALL_TYPES.intersection(sys.argv))
            runArg = runTypeArg.pop()    
        runType = RUN_TYPES[runArg]

        if runType[TYPE] == "naive":
            decisionMaker = NaiveDecisionMakerBattleMngr(GRID_SIZE, runType[RESULTS])
        else:
            decisionMaker = LearnWithReplayMngr(modelType=runType[TYPE], modelParams = runType[PARAMS], decisionMakerName = runType[DECISION_MAKER_NAME],  
                                            resultFileName=runType[RESULTS], historyFileName=runType[HISTORY], directory=AGENT_DIR+runType[DIRECTORY], isMultiThreaded=isMultiThreaded)

        return decisionMaker

    def GetDecisionMaker(self):
        return self.decisionMaker

    def FindActingHeirarchi(self):
        if self.playAgent:
            return 1

        for key, sa in self.subAgents.items():
            if sa.FindActingHeirarchi() >= 0:
                return key
        
        return -1

    def step(self, obs, sharedData = None, moveNum = None):
        super(BattleMngr, self).step(obs)   
        if obs.first():
            self.FirstStep(obs)
            
        if sharedData != None:
            self.sharedData = sharedData
            self.move_number = moveNum

        for sa in self.activeSubAgents:
            self.subAgentsActions[sa] = self.subAgents[sa].step(obs, self.sharedData, self.move_number) 
        
        if self.move_number == 0:
            self.CreateState(obs)
            self.Learn()
            self.current_action = self.ChooseAction()    


        self.numStep += 1        

        return self.current_action

    def FirstStep(self, obs):        
        self.numStep = 0

        self.current_state = np.zeros(self.state_size, dtype=np.int, order='C')
        self.previous_state = np.zeros(self.state_size, dtype=np.int, order='C')
        
        self.current_action = None
        self.isActionCommitted = False

        self.subAgentsActions = {}
        for sa in range(NUM_ACTIONS):
            self.subAgentsActions[sa] = None

    def LastStep(self, obs, reward = 0):

        if self.trainAgent and self.current_action is not None:
            self.decisionMaker.learn(self.current_state.copy(), self.current_action, float(reward), self.terminalState.copy(), True)

            score = obs.observation["score_cumulative"][0]
            self.decisionMaker.end_run(reward, score, self.numStep)
        
        for sa in self.activeSubAgents:
            self.subAgents[sa].LastStep(obs)

    
    def Learn(self, reward = 0):
        if self.trainAgent and self.isActionCommitted:
            self.decisionMaker.learn(self.previous_state.copy(), self.current_action, reward, self.current_state.copy())

        for sa in self.activeSubAgents:
            self.subAgents[sa].Learn(reward)

        self.previous_state[:] = self.current_state[:]
        self.isActionCommitted = False

    def ChooseAction(self):
        if self.playAgent:
            if self.illigalmoveSolveInModel:
                validActions = self.ValidActions()
                if self.trainAgent:
                    targetValues = False
                    exploreProb = self.decisionMaker.ExploreProb()              
                else:
                    targetValues = True
                    exploreProb = 0   

                if np.random.uniform() > exploreProb:
                    valVec = self.decisionMaker.ActionValuesVec(self.current_state, targetValues)   
                    random.shuffle(validActions)
                    validVal = valVec[validActions]
                    action = validActions[validVal.argmax()]
                else:
                    action = np.random.choice(validActions) 
            else:
                action = self.decisionMaker.choose_action(self.current_state)
        else:
            action = self.subAgentPlay

        return action

    def Action2Str(self, a):
        return ACTION2STR[a] + "-->" + self.subAgents[a].Action2Str(self.subAgentsActions[a])

    def IsDoNothingAction(self, a):
        return self.subAgents[a].IsDoNothingAction(self.subAgentsActions[a])

    def Action2SC2Action(self, obs, a, moveNum):
        self.isActionCommitted = True
        self.current_action = a
        return self.subAgents[a].Action2SC2Action(obs, self.subAgentsActions[a], moveNum)

    def CreateState(self, obs):
        self.current_state = np.zeros(self.state_size, dtype=np.int, order='C')
        
        self.GetSelfLoc(obs)
        self.GetEnemyArmyLoc(obs)
        self.GetEnemyBuildingLoc(obs)
        self.current_state[self.state_timeLineIdx] = int(self.numStep / STATE.TIME_LINE_BUCKETING)

    def GetSelfLoc(self, obs):
        playerType = obs.observation["screen"][SC2_Params.PLAYER_RELATIVE]
        unitType = obs.observation["screen"][SC2_Params.UNIT_TYPE]

        allArmy_y = []
        allArmy_x = [] 
        for key, spec in TerranUnit.UNIT_SPEC.items():
            s_y, s_x = ((playerType == SC2_Params.PLAYER_SELF) &(unitType == key)).nonzero()
            allArmy_y += list(s_y)
            allArmy_x += list(s_x)
            
            selfPoints, selfPower = CenterPoints(s_y, s_x)


            for i in range(len(selfPoints)):
                idx = self.GetScaledIdx(selfPoints[i])
                power = math.ceil(selfPower[i] / spec.numScreenPixels)
                self.current_state[STATE.START_SELF_MAT + idx] += power

        if len(allArmy_y) > 0:
            self.selfLocCoord = [int(sum(allArmy_y) / len(allArmy_y)), int(sum(allArmy_x) / len(allArmy_x))]

    def GetEnemyArmyLoc(self, obs):
        playerType = obs.observation["screen"][SC2_Params.PLAYER_RELATIVE]
        unitType = obs.observation["screen"][SC2_Params.UNIT_TYPE]

        enemyPoints = []
        enemyPower = []
        for unit, spec in TerranUnit.UNIT_SPEC.items():
            enemyArmy_y, enemyArmy_x = ((unitType == unit) & (playerType == SC2_Params.PLAYER_HOSTILE)).nonzero()
            unitPoints, unitPower = CenterPoints(enemyArmy_y, enemyArmy_x, spec.numScreenPixels)
            enemyPoints += unitPoints
            enemyPower += unitPower
        
        self.armyExist = False
        for i in range(len(enemyPoints)):
            self.armyExist = True
            idx = self.GetScaledIdx(enemyPoints[i])
            self.current_state[self.state_startEnemyMat + idx] += enemyPower[i]

    def GetEnemyBuildingLoc(self, obs):
        playerType = obs.observation["screen"][SC2_Params.PLAYER_RELATIVE]
        unitType = obs.observation["screen"][SC2_Params.UNIT_TYPE]

        enemyBuildingPoints = []
        enemyBuildingPower = []
        for unit, spec in TerranUnit.BUILDING_SPEC.items():
            enemyArmy_y, enemyArmy_x = ((unitType == unit) & (playerType == SC2_Params.PLAYER_HOSTILE)).nonzero()
            buildingPoints, buildingPower = CenterPoints(enemyArmy_y, enemyArmy_x, spec.numScreenPixels)
            enemyBuildingPoints += buildingPoints
            enemyBuildingPower += buildingPower * self.BuildingValues[spec.name]
        
        self.buildingsExist = False
        for i in range(len(enemyBuildingPoints)):
            self.buildingsExist = True
            idx = self.GetScaledIdx(enemyBuildingPoints[i])
            self.current_state[self.state_startBuildingMat + idx] += enemyBuildingPower[i]
     
       
    def GetScaledIdx(self, screenCord):
        locX = screenCord[SC2_Params.X_IDX]
        locY = screenCord[SC2_Params.Y_IDX]

        yScaled = int((locY / SC2_Params.SCREEN_SIZE) * GRID_SIZE)
        xScaled = int((locX / SC2_Params.SCREEN_SIZE) * GRID_SIZE)

        return xScaled + yScaled * GRID_SIZE
    
    def Closest2Self(self, p1, p2):
        d1 = DistForCmp(p1, self.selfLocCoord)
        d2 = DistForCmp(p2, self.selfLocCoord)
        if d1 < d2:
            return p1
        else:
            return p2
    
    def ValidActions(self):
        valid = [ACTION_DO_NOTHING]
        if self.armyExist:
            valid.append(ACTION_ARMY_BATTLE)
        if self.buildingsExist:
            valid.append(ACTION_BASE_BATTLE)
        
        return valid

    def PrintState(self):
        print("\n\nstate: timeline =", self.current_state[self.state_timeLineIdx])
        for y in range(GRID_SIZE):
            for x in range(GRID_SIZE):
                idx = self.state_startSelfMat + x + y * GRID_SIZE
                print(int(self.current_state[idx]), end = '')
            
            print(end = '  |  ')
            
            for x in range(GRID_SIZE):
                idx = self.state_startEnemyMat + x + y * GRID_SIZE
                print(int(self.current_state[idx]), end = '')

            print(end = '  |  ')
            
            for x in range(GRID_SIZE):
                idx = self.state_startBuildingMat + x + y * GRID_SIZE
                if self.current_state[idx] < 10:
                    print(self.current_state[idx], end = '  ')
                else:
                    print(self.current_state[idx], end = ' ')

            print('||')


if __name__ == "__main__":
    if "plotResults" in sys.argv:
        runTypeArg = list(ALL_TYPES.intersection(sys.argv))
        runTypeArg.sort()
        resultFnames = []
        directoryNames = []
        for arg in runTypeArg:
            runType = RUN_TYPES[arg]
            fName = runType[RESULTS]
            
            if DIRECTORY in runType.keys():
                dirName = runType[DIRECTORY]
            else:
                dirName = ''

            resultFnames.append(fName)
            directoryNames.append(dirName)

        grouping = int(sys.argv[len(sys.argv) - 1])
        plot = PlotMngr(resultFnames, directoryNames, runTypeArg)
        plot.Plot(grouping)