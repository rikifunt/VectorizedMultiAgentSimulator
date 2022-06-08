#  Copyright (c) 2022. Matteo Bettini
#  All rights reserved.

import torch

from maps.simulator.core import Agent, World, Landmark, Sphere
from maps.simulator.scenario import BaseScenario
from maps.simulator.utils import Color


class Scenario(BaseScenario):
    def make_world(self, batch_dim: int, device: torch.device, **kwargs):
        n_agents = kwargs.get("n_agents", 4)
        self.share_reward = kwargs.get("share_reward", False)

        n_food = n_agents

        # Make world
        world = World(batch_dim, device, x_semidim=1, y_semidim=1)
        # Add agents
        for i in range(n_agents):
            # Constraint: all agents have same action range and multiplier
            agent = Agent(
                name=f"agent {i}",
                collide=False,
                shape=Sphere(radius=0.03),
            )
            world.add_agent(agent)
        # Add landmarks
        for i in range(n_food):
            food = Landmark(
                name=f"food {i}",
                collide=False,
                shape=Sphere(radius=0.08),
                color=Color.GREEN,
            )
            world.add_landmark(food)

        return world

    def reset_world_at(self, env_index: int = None):
        for agent in self.world.agents:
            agent.set_pos(
                torch.zeros(
                    self.world.dim_p, device=self.world.device, dtype=torch.float32
                ),
                batch_index=env_index,
            )
        for landmark in self.world.landmarks:
            landmark.set_pos(
                2
                * torch.rand(
                    self.world.dim_p
                    if env_index is not None
                    else (self.world.batch_dim, self.world.dim_p),
                    device=self.world.device,
                    dtype=torch.float32,
                )
                - 1,
                batch_index=env_index,
            )
            if env_index is None:
                landmark.eaten = torch.full(
                    (self.world.batch_dim,), False, device=self.world.device
                )
                landmark.just_eaten = torch.full(
                    (self.world.batch_dim,), False, device=self.world.device
                )
                landmark.reset_render()
            else:
                landmark.eaten[env_index] = False
                landmark.render[env_index] = True

    def reward(self, agent: Agent):
        is_last = agent == self.world.agents[-1]

        rews = torch.zeros(self.world.batch_dim, device=self.world.device)

        for landmark in self.world.landmarks:
            how_many_on_food = torch.stack(
                [
                    torch.sqrt((a.state.pos - landmark.state.pos).square().sum(-1))
                    < a.shape.radius + landmark.shape.radius
                    for a in self.world.agents
                ],
                dim=1,
            ).sum(-1)
            anyone_on_food = how_many_on_food > 0
            landmark.just_eaten[anyone_on_food] = True

            assert (how_many_on_food <= len(self.world.agents)).all()

            if self.share_reward:
                rews[landmark.just_eaten * ~landmark.eaten] += 1
            else:
                on_food = (agent.state.pos - landmark.state.pos).square().sum(
                    -1
                ).sqrt() < agent.shape.radius + landmark.shape.radius
                eating_rew = how_many_on_food.reciprocal().nan_to_num(
                    posinf=0, neginf=0
                )
                rews[on_food * ~landmark.eaten] += eating_rew[on_food * ~landmark.eaten]

            if is_last:
                landmark.eaten += landmark.just_eaten
                landmark.just_eaten[:] = False
                landmark.render[landmark.eaten] = False

        rews[rews == 0] = -0.01
        return rews

    def observation(self, agent: Agent):
        obs = []
        for entity in self.world.landmarks:
            obs.append(
                torch.cat(
                    [
                        entity.state.pos - agent.state.pos,
                        entity.eaten.to(torch.int).unsqueeze(-1),
                    ],
                    dim=-1,
                )
            )
        return torch.cat(
            [agent.state.pos, *obs],
            dim=-1,
        )

    def done(self):
        return torch.all(
            torch.stack(
                [l.eaten for l in self.world.landmarks],
                dim=1,
            ),
            dim=-1,
        )