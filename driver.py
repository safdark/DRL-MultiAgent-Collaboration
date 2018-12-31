
from unityagents import UnityEnvironment
from trainer import Trainer
from tracker import PerformanceTracker
from agent import AgentFactory
from tracker import TrackerFactory
import time

def main():
    print("Training the agent ...")
    env = UnityEnvironment(file_name='Tennis_Linux/Tennis.x86_64')
    agent_factory = AgentFactory()
    tracker_factory = TrackerFactory()
    trainer = Trainer(env, agent_factory, tracker_factory)
    trainer.describe_environment()
    time.sleep(5)
    agent, tracker = trainer.train(n_episodes=2000, plot_every=3000, learn_every=10, iterations_per_learn=10, save_every=1000, goal_score=0.5)
    print("Training complete!")
    time.sleep(5)

    print("Running the trained agent ...")
    trainer.play(agent)
    time.sleep(10)
    env.close()
    print("Game finished!")

    print("Training performance")
    tracker.plot_performance()

    time.sleep(5)



if __name__ == '__main__':
    # import cProfile
    # cp = cProfile.Profile()
    # cp.enable()

    main()

    # cp.disable()