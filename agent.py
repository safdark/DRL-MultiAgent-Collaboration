import numpy as np
import random
import copy
import os
from collections import namedtuple, deque
from feature_extractor import DisambiguatingFeatureExtractor

from model import Actor, Critic

import torch
import torch.nn.functional as F
import torch.optim as optim

BATCH_SIZE = 514      # minibatch size         512=10s/episode, 256=7s/episode, 128=6s/episode, 64=5s, 32=4.5s, 16=4s
BUFFER_SIZE = int(1e5)  # replay buffer size
GAMMA = 0.99            # discount factor
TAU = 0.15              # for soft update of target parameters
LR_ACTOR = 1e-3         # learning rate of the actor 
LR_CRITIC = 1e-3        # learning rate of the critic
WEIGHT_DECAY = 0.00        # L2 weight decay

class AgentFactory(object):
    def __init__(self):
        pass
    
    def createAgent(self, state_size, action_size, random_seed, learn_every=None, iterations_per_learn=None):
        return DDPGAgent(state_size, action_size, random_seed, learn_every, iterations_per_learn)

class DDPGAgent():
    """Interacts with and learns from the environment."""
    
    def __init__(self, state_size, action_size, random_seed, learn_every=None, iterations_per_learn=None):
        """Initialize an Agent object.
        
        Params
        ======
            state_size (int): dimension of each state
            action_size (int): dimension of each action
            random_seed (int): random seed
        """
        self.device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
        print ("Agent is using: ", self.device)
        self.feature_extractor = DisambiguatingFeatureExtractor()
        self.state_size = self.feature_extractor.estimate_state_size(state_size)
        self.action_size = action_size

        # Seed the random number generators:
        random.seed(random_seed)
        np.random.seed(random_seed)

        self.learn_every = learn_every
        self.iterations_per_learn = iterations_per_learn

        # Actor Network (w/ Target Network)
        self.actor_local = Actor(self.state_size, action_size, np.random.randn()).to(self.device)
        self.actor_target = Actor(self.state_size, action_size, np.random.randn()).to(self.device)
        self.actor_optimizer = optim.Adam(self.actor_local.parameters(), lr=LR_ACTOR)

        # Critic Network (w/ Target Network)
        self.critic_local = Critic(self.state_size, action_size, np.random.randn()).to(self.device)
        self.critic_target = Critic(self.state_size, action_size, np.random.randn()).to(self.device)
        self.critic_optimizer = optim.Adam(self.critic_local.parameters(), lr=LR_CRITIC, weight_decay=WEIGHT_DECAY)

        # Noise process
        self.noise = OUNoise(action_size)

        # Replay memory
        self.step_count = 0
        self.memory = ReplayBuffer(action_size, BUFFER_SIZE, BATCH_SIZE, self.device)
    
    def save(self, fileprefix):
        """Save the Q-network aprameters to the given file.
        
        Params
        ======
            checkpoint_file (string): path of the file into which to save the parameters
        """
        assert fileprefix is not None, "Invalid 'fileprefix' was provided: {}".format(fileprefix)
        torch.save(self.actor_local.state_dict(), fileprefix+"_actor_local.pth")
        torch.save(self.actor_target.state_dict(), fileprefix+"_actor_target.pth")
        torch.save(self.critic_local.state_dict(), fileprefix+"_critic_local.pth")
        torch.save(self.critic_target.state_dict(), fileprefix+"_critic_target.pth")

    def load(self, fileprefix):
        """Load the Q-network aprameters from the given file.
        
        Params
        ======
            checkpoint_file (string): path of the file from which to load the parameters
        """
        if os.path.exists(self.save_file+"_actor_local.pth") is True:
            self.actor_local.load_state_dict(torch.load(fileprefix+"_actor_local.pth"))
            self.actor_target.load_state_dict(torch.load(fileprefix+"_actor_target.pth"))
            self.critic_local.load_state_dict(torch.load(fileprefix+"_critic_local.pth"))
            self.critic_target.load_state_dict(torch.load(fileprefix+"_critic_target.pth"))
            print ("Checkpoint files for '{}' FOUND and loaded by agent!".format(self.save_file))
        else:
            print ("Checkpoint files for '{}' NOT found. Proceeding without.".format(self.save_file))

    def step(self, states, actions, rewards, next_states, dones):
        """Save experience in replay memory, and use random sample from buffer to learn."""
        self.step_count += 1

        assert len(states.shape) >= 2, "Expected a state vector of at least 2 dimensions, but was only {} dimensions ({})".format(len(states.shape), states.shape)
        states = self.feature_extractor.extract_states(states)
        next_states = self.feature_extractor.extract_states(next_states)
        for state, action, reward, next_state, done in zip(states, actions, rewards, next_states, dones):
            self.memory.add(state, action, reward, next_state, done)

        # Learn, if enough samples are available in memory
        if ((len(self.memory) > BATCH_SIZE) and (self.step_count % self.learn_every == 0)):
            for i in range(self.iterations_per_learn):
                experiences = self.memory.sample()
                self.learn(experiences, GAMMA)

    def act(self, states, add_noise=True):
        """Returns actions for given states as per current policy."""
        states = self.feature_extractor.extract_states(states)
        states = torch.from_numpy(states).float().to(self.device)
        self.actor_local.eval()
        with torch.no_grad():
            action = self.actor_local(states).cpu().data.numpy()
        self.actor_local.train()
        if add_noise:
            action += self.noise.sample_stack(states.shape[0])
        return np.clip(action, -1, 1)

    def reset(self):
        self.noise.reset()
        # self.step_count = 0

    def learn(self, experiences, gamma):
        """Update policy and value parameters using given batch of experience tuples.
        Q_targets = r + γ * critic_target(next_state, actor_target(next_state))
        where:
            actor_target(state) -> action
            critic_target(state, action) -> Q-value

        Params
        ======
            experiences (Tuple[torch.Tensor]): tuple of (s, a, r, s', done) tuples 
            gamma (float): discount factor
        """
        states, actions, rewards, next_states, dones = experiences

        # ---------------------------- update critic ---------------------------- #
        # Get predicted next-state actions and Q values from target models
        actions_next = self.actor_target(next_states)
        Q_targets_next = self.critic_target(next_states, actions_next)
        # Compute Q targets for current states (y_i)
        Q_targets = rewards + (gamma * Q_targets_next * (1 - dones))
        # Compute critic loss
        Q_expected = self.critic_local(states, actions)
        critic_loss = F.mse_loss(Q_expected, Q_targets)
        # Minimize the loss
        self.critic_optimizer.zero_grad()
        critic_loss.backward()
        torch.nn.utils.clip_grad_norm_(self.critic_local.parameters(), 1)
        self.critic_optimizer.step()

        # ---------------------------- update actor ---------------------------- #
        # Compute actor loss
        actions_pred = self.actor_local(states)
        actor_loss = -self.critic_local(states, actions_pred).mean()
        # Minimize the loss
        self.actor_optimizer.zero_grad()
        actor_loss.backward()
        self.actor_optimizer.step()

        # ----------------------- update target networks ----------------------- #
        self.soft_update(self.critic_local, self.critic_target, TAU)
        self.soft_update(self.actor_local, self.actor_target, TAU)                     

    def soft_update(self, local_model, target_model, tau):
        """Soft update model parameters.
        θ_target = τ*θ_local + (1 - τ)*θ_target

        Params
        ======
            local_model: PyTorch model (weights will be copied from)
            target_model: PyTorch model (weights will be copied to)
            tau (float): interpolation parameter 
        """
        for target_param, local_param in zip(target_model.parameters(), local_model.parameters()):
            target_param.data.copy_(tau*local_param.data + (1.0-tau)*target_param.data)

class OUNoise:
    """Ornstein-Uhlenbeck process."""

    def __init__(self, size, mu=0., theta=0.15, sigma=0.2):
        """Initialize parameters and noise process."""
        self.size = size
        self.mu = mu * np.ones(self.size)
        self.theta = theta
        self.sigma = sigma
        self.reset()

    def reset(self):
        """Reset the internal state (= noise) to mean (mu)."""
        self.state = copy.copy(self.mu)

    def sample_stack(self, num_perspectives=1):
        sample = np.zeros((num_perspectives, self.size), dtype=np.float32)
        for i in range(num_perspectives):
            sample[i] = self.__sample__()
        return sample;

    def __sample__(self):
        """Update internal state and return it as a noise sample."""
        x = self.state
        dx = self.theta * (self.mu - x) + self.sigma * np.array([np.random.randn() for i in range(len(x))])
        self.state = x + dx
        return self.state

class ReplayBuffer:
    """Fixed-size buffer to store experience tuples."""

    def __init__(self, action_size, buffer_size, batch_size, device):
        """Initialize a ReplayBuffer object.
        Params
        ======
            buffer_size (int): maximum size of buffer
            batch_size (int): size of each training batch
        """
        self.device = device
        self.action_size = action_size
        self.memory = deque(maxlen=buffer_size)  # internal memory (deque)
        self.batch_size = batch_size
        self.experience = namedtuple("Experience", field_names=["state", "action", "reward", "next_state", "done"])
    
    def add(self, state, action, reward, next_state, done):
        """Add a new experience to memory."""
        e = self.experience(state, action, reward, next_state, done)
        self.memory.append(e)
    
    def sample(self):
        """Randomly sample a batch of experiences from memory."""
        experiences, device = random.sample(self.memory, k=self.batch_size), self.device

        states = torch.from_numpy(np.vstack([e.state for e in experiences if e is not None])).float().to(device)
        actions = torch.from_numpy(np.vstack([e.action for e in experiences if e is not None])).float().to(device)
        rewards = torch.from_numpy(np.vstack([e.reward for e in experiences if e is not None])).float().to(device)
        next_states = torch.from_numpy(np.vstack([e.next_state for e in experiences if e is not None])).float().to(device)
        dones = torch.from_numpy(np.vstack([e.done for e in experiences if e is not None]).astype(np.uint8)).float().to(device)

        return (states, actions, rewards, next_states, dones)

    def __len__(self):
        """Return the current size of internal memory."""
        return len(self.memory)