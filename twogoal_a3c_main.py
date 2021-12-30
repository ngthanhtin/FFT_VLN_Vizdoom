import vizdoom
import argparse
import os
os.environ["OMP_NUM_THREADS"] = "1"
import numpy as np
import torch
import torch.multiprocessing as mp

import env.multigoal_env as grounding_env
from models.models import A3C_LSTM_GA
from twogoal_a3c_train import train
from twogoal_a3c_test import test
from ae.auto_encoder import Auto_Encoder_Model_PReLu224

torch.multiprocessing.set_start_method('spawn', force=True)


parser = argparse.ArgumentParser(description='Instruction Navigation in Vizdoom')

# Environment arguments
parser.add_argument('-l', '--max-episode-length', type=int, default=60, # 30 for single goal, 60 for multiple goals
                    help='maximum length of an episode (default: 30)')
parser.add_argument('-d', '--difficulty', type=str, default="hard",
                    help="""Difficulty of the environment,
                    "easy", "medium" or "hard" (default: hard)""")
parser.add_argument('--living-reward', type=float, default=0,
                    help="""Default reward at each time step (default: 0,
                    change to -0.005 to encourage shorter paths)""")
parser.add_argument('--frame-width', type=int, default=300,
                    help='Frame width (default: 300)')
parser.add_argument('--frame-height', type=int, default=168,
                    help='Frame height (default: 168)')
parser.add_argument('-v', '--visualize', type=int, default=0,
                    help="""Visualize the envrionment (default: 0,
                    use 0 for faster training)""")
parser.add_argument('--sleep', type=float, default=0,
                    help="""Sleep between frames for better
                    visualization (default: 0)""")
parser.add_argument('--scenario-path', type=str, default="maps/room.wad",
                    help="""Doom scenario file to load
                    (default: maps/room.wad)""")
parser.add_argument('--interactive', type=int, default=0,
                    help="""Interactive mode enables human to play
                    (default: 0)""")
parser.add_argument('--all-instr-file', type=str,
                    # default="data/multigoal_instruction/multigoal_instructions_all.json", # error , fix later
                    default="data/instructions_all.json",
                    help="""All instructions file
                    (default: data/instructions_all.json)""")
parser.add_argument('--train-instr-file', type=str,
                    default="data/multigoal_instruction/twogoal_instructions_train.json",
                    help="""Train instructions file
                    (default: data/instructions_train.json)""")
parser.add_argument('--test-instr-file', type=str,
                    default="data/multigoal_instruction/twogoal_instructions_test.json",
                    help="""Test instructions file
                    (default: data/instructions_test.json)""")
parser.add_argument('--object-size-file', type=str,
                    default="data/object_sizes.txt",
                    help='Object size file (default: data/object_sizes.txt)')

# A3C arguments
parser.add_argument('--lr', type=float, default=0.001, metavar='LR',
                    help='learning rate (default: 0.001)')
parser.add_argument('--gamma', type=float, default=0.99, metavar='G',
                    help='discount factor for rewards (default: 0.99)')
parser.add_argument('--tau', type=float, default=1.00, metavar='T',
                    help='parameter for GAE (default: 1.00)')
parser.add_argument('--seed', type=int, default=1, metavar='S',
                    help='random seed (default: 1)')
parser.add_argument('-n', '--num-processes', type=int, default=4, metavar='N',
                    help='how many training processes to use (default: 4)')
parser.add_argument('--num-steps', type=int, default=20, metavar='NS',
                    help='number of forward steps in A3C (default: 20)')
parser.add_argument('--load', type=str, default="0",
                    help='model path to load, 0 to not reload (default: 0)')
parser.add_argument('-e', '--evaluate', type=int, default=0,
                    help="""0:Train, 1:Evaluate MultiTask Generalization
                    2:Evaluate Zero-shot Generalization (default: 0)""")
parser.add_argument('--dump-location', type=str, default="./saved/",
                    help='path to dump models and log (default: ./saved/)')

# Attention arguments
parser.add_argument('-att', '--attention', type=str, default="fga",
                    help="""Type of attention,
                    "fga" or "ga" or "convolve" (default: fga)""")

#AE arguments
parser.add_argument('--auto-encoder', action='store_true',
                    help='use AE or not')
parser.add_argument('--ae-model-path', type=str, default="./ae/ae_full_prelu_224.pth",
                    help='pretrained AE model')

def count_parameters(model):
    return sum(p.numel() for p in model.parameters() if p.requires_grad)

if __name__ == '__main__':
    args = parser.parse_args()

    if args.evaluate == 0:
        args.use_train_instructions = 1
        log_filename = "train.log"
    elif args.evaluate == 1:
        args.use_train_instructions = 1
        args.num_processes = 0
        log_filename = "test-MT.log"
    elif args.evaluate == 2:
        args.use_train_instructions = 0
        args.num_processes = 0
        log_filename = "test-ZSL.log"
    else:
        assert False, "Invalid evaluation type"

    env = grounding_env.MultiGoal_GroundingEnv(args)
    args.vocab_size = len(env.word_to_idx)
    args.dictionary = env.word_to_idx
    with open("dict.txt", "w") as f:
            f.write("{}\n".format(args.dictionary))
    
    ae_model = None
    if args.auto_encoder:
        ae_model = Auto_Encoder_Model_PReLu224()
        # pytorch_total_params = sum(p.numel() for p in ae_model.parameters())
        # print(pytorch_total_params)
        print('Loading initial weights CDAE from: %s'%(args.ae_model_path))
        ae_model.load_state_dict(torch.load(args.ae_model_path, map_location=torch.device('cpu')))
        print("Loaded AE model")

    shared_model = A3C_LSTM_GA(args, ae_model)
    

    pytorch_total_params = sum(p.numel() for p in shared_model.parameters())

    # Load the model
    if (args.load != "0"):
        shared_model.load_state_dict(
            torch.load(args.load, map_location=lambda storage, loc: storage))

    shared_model.share_memory()

    processes = []

    # Start the test thread
    p = mp.Process(target=test, args=(args.num_processes, args, shared_model))
    p.start()
    processes.append(p)

    # Start the training thread(s)
    for rank in range(0, args.num_processes):
        p = mp.Process(target=train, args=(rank, args, shared_model))
        p.start()
        processes.append(p)
    for p in processes:
        p.join()
