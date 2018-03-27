from torch.autograd import Variable
import torch.nn  as nn
from utils.utils import select_action

# Only one episode (Remember, end of life = end of episode for DQN)
def trainDQN(env, model, target_model, optimizer, value_criterion, args):
    model.train()
    state = env.reset()
    done = False
    initial_frame = args.current_frame
    loss = 0
    # Handle training for one episode
    while not done:
        # Sample noise if needed:
        if args.noise == 'learned':
            model.resample()
        elif args.noise == 'adaptive':
            model.eval()
            model.renoise()
            model.resample()

        # Take a step
        action = select_action(state, model, args)
        successor, reward, done, _ = env.step(action)
        args.memory.add(state, action, reward, successor, done)

        # Sample from replay buffer and prepare
        states, actions, rewards, successors, dones = args.memory.sample(args.batch_size)
        final_mask = args.ByteTensor(tuple(map(lambda s: s is None, successors)))
        states = Variable(states)
        actions = Variable(actions)
        rewards = Variable(rewards)

        # Handle noise stuff if needed
        if args.noise == 'adaptive':
            model.denoise()
            target_model.denoise()
            model.train()

        # Compute terms for network update
        # In regards to commit 74c2315:
        # Reached out to the folks at DeepMind, they
        # said sampling noise for each batch is sufficient
        # Q_head is used for adaptive
        Q_head = model(states)
        Q = Q_head.max(1)[0]
        states.volatile = True
        target_Q = target_model(states).max(1)[0]
        target_Q[final_mask] = 0
        target_Q.volatile = False
        expected_Q = args.discount_factor * target_Q + rewards

        # Compute loss, backpropagate and apply clipped gradient update
        loss = value_criterion(Q, expected_Q)
        optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm(model.parameters(), 10.)
        optimizer.step()

        # Sync target network if needed
        if args.current_frame % args.sync_every == args.sync_every - 1:
            target_model.load_state_dict(model.state_dict())

        # Adapt if needed
        if args.noise == 'adaptive' and args.current_frame % args.adapt_every == args.adapt_every - 1:
            model.renoise()
            perturbed_output = model(states)
            Q_head = Q_head.detach()
            distance = model.adaptive_metric(Q_head, perturbed_output)
            model.adapt(distance)

        # Update frame-level meters
        args.losses.update(loss.data[0])
        args.rewards.update(float(reward))

        # Move on
        state = successor
        args.current_frame += 1

        # Update progress bar every frame
        args.bar.suffix = '({frame}/{size}) | Total: {total:} | ETA: {eta:} | AvgLoss: {loss:.4f} | AvgReward: {rewards: .4f}'.format(
                    frame=args.current_frame,
                    size=args.n_frames,
                    #data=data_time.avg,
                    #bt=batch_time.avg,
                    total=args.bar.elapsed_td,
                    eta=args.bar.eta_td,
                    loss=args.losses.avg,
                    rewards=args.rewards.avg)
        args.bar.next()

    # Update episode-level meters
    args.returns.update(args.rewards.sum)
    args.episode_lengths.update(int(args.current_frame - initial_frame))

    args.bar.suffix += ' | Total Loss {loss} | Return {return_} | Episode Length {length}\n'.format(
                loss=round(args.losses.sum, 4),
                return_=args.returns.val,
                length=args.episode_lengths.val)
    args.bar.next()


    # Initiate evaluation if needed
    if args.current_frame - args.eval_start > args.eval_every:
        args.test_time = True

    return env, model, target_model, optimizer, args


def trainPPO(env, model, optimizer, value_criterion, policy_criterion, args):
    model.train()
    state = env.reset()
    return env, model, optimizer, args
