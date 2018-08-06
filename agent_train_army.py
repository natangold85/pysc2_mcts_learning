# train army sub agent
import random
import math
import os.path
import sys

import numpy as np
import pandas as pd

from pysc2.lib import actions

from utils import BaseAgent

from utils import TerranUnit
from utils import SC2_Params
from utils import SC2_Actions

#decision makers
from utils_decisionMaker import LearnWithReplayMngr
from utils_decisionMaker import UserPlay

# params
from utils_dqn import DQN_PARAMS
from utils_dqn import DQN_EMBEDDING_PARAMS
from utils_qtable import QTableParams
from utils_qtable import QTableParamsExplorationDecay

from utils import EmptySharedData
from utils import SwapPnt
from utils import FindMiddle
from utils import GetScreenCorners
from utils import IsolateArea
from utils import Scale2MiniMap
from utils import GetLocationForBuildingAddition
from utils import GetUnitId
from utils import SelectBuildingValidPoint

from agent_build_base import ActionRequirement

AGENT_DIR = "TrainArmy/"
if not os.path.isdir("./" + AGENT_DIR):
    os.makedirs("./" + AGENT_DIR)

AGENT_NAME = "trainer"

# possible types of decision maker

QTABLE = 'q'
DQN = 'dqn'
DQN_EMBEDDING_LOCATIONS = 'dqn_Embedding' 

USER_PLAY = 'play'

ALL_TYPES = set([USER_PLAY, QTABLE, DQN, DQN_EMBEDDING_LOCATIONS])

# data for run type
TYPE = "type"
DECISION_MAKER_NAME = "dm_name"
HISTORY = "hist"
RESULTS = "results"
PARAMS = 'params'
DIRECTORY = 'directory'


ID_ACTION_DO_NOTHING = 0
ID_ACTION_TRAIN_MARINE = 1
ID_ACTION_TRAIN_REAPER = 2
ID_ACTION_TRAIN_HELLION = 3
ID_ACTION_TRAIN_SIEGETANK = 4

NUM_ACTIONS = 5

ACTION2STR = ["DoNothing" , "TrainMarine", "TrainReaper", "TrainHellion", "TrainSiegeTank"]

ACTION_2_UNIT = {}
ACTION_2_UNIT[ID_ACTION_TRAIN_MARINE] = GetUnitId("marine")
ACTION_2_UNIT[ID_ACTION_TRAIN_REAPER] = GetUnitId("reaper")
ACTION_2_UNIT[ID_ACTION_TRAIN_HELLION] = GetUnitId("hellion")
ACTION_2_UNIT[ID_ACTION_TRAIN_SIEGETANK] = GetUnitId("siege tank")

# state details
STATE_NON_VALID_NUM = -1

STATE_MINERALS_MAX = 500
STATE_GAS_MAX = 300
STATE_MINERALS_BUCKETING = 50
STATE_GAS_BUCKETING = 50

STATE_MINERALS_IDX = 0
STATE_GAS_IDX = 1
STATE_SUPPLY_DEPOT_IDX = 2
STATE_BARRACKS_IDX = 3
STATE_FACTORY_IDX = 4
STATE_REACTORS_IDX = 5
STATE_TECHLAB_IDX = 6
STATE_ARMY_POWER = 7
STATE_QUEUE_BARRACKS = 8
STATE_QUEUE_FACTORY = 9
STATE_QUEUE_FACTORY_WITH_TECHLAB = 10
STATE_SIZE = 11

STATE_IDX2STR = ["min", "gas", "sd", "ba", "fa", "re", "te", "power", "ba_q", "fa_q", "te_q"]

BUILDING_2_STATE_TRANSITION = {}
BUILDING_2_STATE_TRANSITION[TerranUnit.SUPPLY_DEPOT] = STATE_SUPPLY_DEPOT_IDX
BUILDING_2_STATE_TRANSITION[TerranUnit.BARRACKS] = STATE_BARRACKS_IDX
BUILDING_2_STATE_TRANSITION[TerranUnit.FACTORY] = STATE_FACTORY_IDX
BUILDING_2_STATE_TRANSITION[TerranUnit.REACTOR] = STATE_REACTORS_IDX
BUILDING_2_STATE_TRANSITION[TerranUnit.TECHLAB] = STATE_TECHLAB_IDX

BUILDING_2_STATE_QUEUE_TRANSITION = {}

BUILDING_2_STATE_QUEUE_TRANSITION[TerranUnit.BARRACKS] = STATE_QUEUE_BARRACKS
BUILDING_2_STATE_QUEUE_TRANSITION[TerranUnit.FACTORY] = STATE_QUEUE_FACTORY
BUILDING_2_STATE_QUEUE_TRANSITION[TerranUnit.TECHLAB] = STATE_QUEUE_FACTORY_WITH_TECHLAB

class SharedDataTrain(EmptySharedData):
    def __init__(self):
        super(SharedDataTrain, self).__init__()

        self.trainingQueue = {}
        for key in BUILDING_2_STATE_QUEUE_TRANSITION.keys():
            self.trainingQueue[key] = []

        self.armySize = {}
        self.unitTrainValue = {}
        for unit in ACTION_2_UNIT.values():
            self.armySize[unit] = 0
            self.unitTrainValue[unit] = 0.0

        self.prevActionReward = 0.0




class TrainCmd:
    def __init__(self, unitId):
        self.unitId = unitId
        self.stepsCounter = 0

DO_NOTHING_SC2_ACTION = actions.FunctionCall(SC2_Actions.NO_OP, [])

# table names
RUN_TYPES = {}

RUN_TYPES[QTABLE] = {}
RUN_TYPES[QTABLE][TYPE] = "QLearningTable"
RUN_TYPES[QTABLE][PARAMS] = QTableParamsExplorationDecay(STATE_SIZE, NUM_ACTIONS)
RUN_TYPES[QTABLE][DIRECTORY] = "trainArmy_qtable"
RUN_TYPES[QTABLE][DECISION_MAKER_NAME] = "qtable"
RUN_TYPES[QTABLE][HISTORY] = "replayHistory"
RUN_TYPES[QTABLE][RESULTS] = "result"

RUN_TYPES[DQN] = {}
RUN_TYPES[DQN][TYPE] = "DQN_WithTarget"
RUN_TYPES[DQN][PARAMS] = DQN_PARAMS(STATE_SIZE, NUM_ACTIONS)
RUN_TYPES[DQN][DECISION_MAKER_NAME] = "train_dqn"
RUN_TYPES[DQN][DIRECTORY] = "trainArmy_dqn"
RUN_TYPES[DQN][HISTORY] = "replayHistory"
RUN_TYPES[DQN][RESULTS] = "result"


class TrainArmySubAgent(BaseAgent):
    def __init__(self, runArg = None, decisionMaker = None, isMultiThreaded = False, playList = None, trainList = None):     
        super(TrainArmySubAgent, self).__init__()     

        self.playAgent = (AGENT_NAME in playList) | ("inherit" in playList)
        self.trainAgent = AGENT_NAME in trainList
        
        self.illigalmoveSolveInModel = True

        # tables:
        if decisionMaker != None:
            self.decisionMaker = decisionMaker
        else:
            self.decisionMaker = self.CreateDecisionMaker(runArg, isMultiThreaded)

        if not self.playAgent:
            self.subAgentPlay = self.FindActingHeirarchi()

        # model params
        self.unit_type = None

        self.cameraCornerNorthWest = [-1,-1]
        self.cameraCornerSouthEast = [-1,-1]

        self.currentBuildingTypeSelected = TerranUnit.BARRACKS
        self.currentBuildingCoordinate = [-1,-1]

        self.actionsRequirement = {}
        self.actionsRequirement[ID_ACTION_TRAIN_MARINE] = ActionRequirement(50, 0, TerranUnit.BARRACKS)
        self.actionsRequirement[ID_ACTION_TRAIN_REAPER] = ActionRequirement(50, 50, TerranUnit.BARRACKS)
        self.actionsRequirement[ID_ACTION_TRAIN_HELLION] = ActionRequirement(100, 0, TerranUnit.FACTORY)
        self.actionsRequirement[ID_ACTION_TRAIN_SIEGETANK] = ActionRequirement(150, 125, TerranUnit.TECHLAB)

    def CreateDecisionMaker(self, runArg, isMultiThreaded):
        if runArg == None:
            runTypeArg = list(ALL_TYPES.intersection(sys.argv))
            runArg = runTypeArg.pop()    
        runType = RUN_TYPES[runArg]

        decisionMaker = LearnWithReplayMngr(modelType=runType[TYPE], modelParams = runType[PARAMS], decisionMakerName = runType[DECISION_MAKER_NAME],  
                                        resultFileName=runType[RESULTS], historyFileName=runType[HISTORY], directory=AGENT_DIR + runType[DIRECTORY], isMultiThreaded=isMultiThreaded)

        return decisionMaker

    def GetDecisionMaker(self):
        return self.decisionMaker

    def FindActingHeirarchi(self):
        if self.playAgent:
            return 1
        
        return -1
        
    def step(self, obs, sharedData = None, moveNum = None):  
        super(TrainArmySubAgent, self).step(obs) 

        self.cameraCornerNorthWest , self.cameraCornerSouthEast = GetScreenCorners(obs)
        self.unit_type = obs.observation['screen'][SC2_Params.UNIT_TYPE]
        
        if obs.first():
            self.FirstStep(obs)
        
        if sharedData != None:
            self.sharedData = sharedData

        if moveNum == 0: 
            self.CreateState(obs)
            self.current_action = self.ChooseAction()
        
        self.numSteps += 1

        return self.current_action

    def FirstStep(self, obs):
        # states and action:
        self.current_action = None
        self.previous_state = np.zeros(STATE_SIZE, dtype=np.int32, order='C')
        self.current_state = np.zeros(STATE_SIZE, dtype=np.int32, order='C')
        self.previous_scaled_state = np.zeros(STATE_SIZE, dtype=np.int32, order='C')
        self.current_scaled_state = np.zeros(STATE_SIZE, dtype=np.int32, order='C')

        self.numSteps = 0

        self.sharedData = SharedDataTrain()
        self.isActionCommitted = False
        self.lastActionCommittedAction = None

    def IsDoNothingAction(self, a):
        return a == ID_ACTION_DO_NOTHING

    def LastStep(self, obs, reward):
        if self.trainAgent and self.lastActionCommittedAction is not None:
            self.decisionMaker.learn(self.lastActionCommittedState.copy(), self.lastActionCommittedAction, reward, self.lastActionCommittedNextState.copy(), True)

            score = obs.observation["score_cumulative"][0]
            self.decisionMaker.end_run(reward, score, self.numSteps)

    def Action2SC2Action(self, obs, a, moveNum):
        self.isActionCommitted = True
        if moveNum == 0:
            finishedAction = False
            buildingType = self.BuildingType(a)
            target = SelectBuildingValidPoint(self.unit_type, buildingType)
            if target[0] >= 0:
                return actions.FunctionCall(SC2_Actions.SELECT_POINT, [SC2_Params.SELECT_ALL, SwapPnt(target)]), finishedAction
        if moveNum == 1:
            finishedAction = True
            unit2Train = ACTION_2_UNIT[a]
            sc2Action = TerranUnit.UNIT_2_SC2ACTIONS[unit2Train]
            if sc2Action in obs.observation['available_actions']:
                self.sharedData.prevActionReward = self.sharedData.unitTrainValue[unit2Train]

                buildingReq4Train = self.actionsRequirement[a].buildingDependency
                self.sharedData.trainingQueue[buildingReq4Train].append(TrainCmd(unit2Train))
                return actions.FunctionCall(sc2Action, [SC2_Params.QUEUED]), finishedAction

        return DO_NOTHING_SC2_ACTION, True

    def Learn(self, reward = 0):
        if self.trainAgent and self.isActionCommitted:
            self.decisionMaker.learn(self.previous_scaled_state, self.current_action, reward, self.current_scaled_state)
        
        self.previous_state[:] = self.current_state[:]
        self.previous_scaled_state[:] = self.current_scaled_state[:]
        self.isActionCommitted = False

    def CreateState(self, obs):
        self.current_state[STATE_MINERALS_IDX] = obs.observation['player'][SC2_Params.MINERALS]
        self.current_state[STATE_GAS_IDX] = obs.observation['player'][SC2_Params.VESPENE]
        for key, value in BUILDING_2_STATE_TRANSITION.items():
            self.current_state[value] = self.sharedData.buildingCount[key]

        for key, value in BUILDING_2_STATE_QUEUE_TRANSITION.items():
            self.current_state[value] = len(self.sharedData.trainingQueue[key])
        
        power = 0.0
        for unit, num in self.sharedData.armySize.items():
            power += num * self.sharedData.unitTrainValue[unit]
        
        self.current_state[STATE_ARMY_POWER] = round(power)

        self.ScaleState()

        if self.isActionCommitted:
            self.lastActionCommittedAction = self.current_action
            self.lastActionCommittedState = self.previous_scaled_state
            self.lastActionCommittedNextState = self.current_scaled_state

    def ScaleState(self):
        self.current_scaled_state[:] = self.current_state[:]

        self.current_scaled_state[STATE_MINERALS_IDX] = int(self.current_scaled_state[STATE_MINERALS_IDX] / STATE_MINERALS_BUCKETING) * STATE_MINERALS_BUCKETING
        self.current_scaled_state[STATE_MINERALS_IDX] = min(STATE_MINERALS_MAX, self.current_scaled_state[STATE_MINERALS_IDX])
        self.current_scaled_state[STATE_GAS_IDX] = int(self.current_scaled_state[STATE_GAS_IDX] / STATE_GAS_BUCKETING) * STATE_GAS_BUCKETING
        self.current_scaled_state[STATE_GAS_IDX] = min(STATE_GAS_MAX, self.current_scaled_state[STATE_GAS_IDX])

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

    def ValidActions(self):
        valid = [ID_ACTION_DO_NOTHING]
        for key, requirement in self.actionsRequirement.items():
            if self.ValidSingleAction(requirement):
                valid.append(key)
        return valid

    def ValidSingleAction(self, requirement):
        hasMinerals = self.current_scaled_state[STATE_MINERALS_IDX] >= requirement.mineralsPrice
        hasGas = self.current_scaled_state[STATE_GAS_IDX] >= requirement.gasPrice
        idx = BUILDING_2_STATE_TRANSITION[requirement.buildingDependency]
        otherReq = self.current_scaled_state[idx] > 0
        return hasMinerals & hasGas & otherReq

    def BuildingType(self, action):
        if action > ID_ACTION_DO_NOTHING:
            if action > ID_ACTION_TRAIN_REAPER:
                return TerranUnit.FACTORY
            else:
                return TerranUnit.BARRACKS
        else:
            return None

    def Action2Str(self,a):
        print("train action =", a)
        return ACTION2STR[a]

    def PrintState(self):
        for i in range(STATE_SIZE):
            print(STATE_IDX2STR[i], self.current_scaled_state[i], end = ', ')

        print("")