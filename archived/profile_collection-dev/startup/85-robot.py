import asyncio
from ophyd import Device, EpicsSignal, EpicsSignalRO
from ophyd import Component as C
from ophyd.utils import set_and_wait
from bluesky import Msg
from bluesky.plans import subs_wrapper, count, list_scan, single_gen
from bluesky.callbacks import LiveTable


class Robot(Device):
    sample_number = Cpt(EpicsSignal, 'ID:Tgt-SP')
    load_cmd = Cpt(EpicsSignal, 'Cmd:Load-Cmd.PROC')
    unload_cmd = Cpt(EpicsSignal, 'Cmd:Unload-Cmd.PROC')
    execute_cmd = Cpt(EpicsSignal, 'Cmd:Exec-Cmd')
    status = Cpt(EpicsSignal, 'Sts-Sts')
    current_sample_number = Cpt(EpicsSignalRO, 'Addr:CurrSmpl-I')
 
    # Map sample types to their load position and measurement position.
    TH_POS = {'capillary': {'load': 90, 'measure': 90},
              'plate': {'load': 90, 'measure': 180}, 
              None: {'load': 90, 'measure': 90}}

    DIFF_POS = {'capilary': (1,2),}

    def __init__(self, *args, theta, diff=None, **kwargs):
        """
        Parameters
        ----------
        theta : motor
        diff : motor, optional [not currently used]
        """
        self.theta = theta
        self._current_sample_geometry = None
        super().__init__(*args, **kwargs)

    def _poll_until_idle(self):
        time.sleep(3)  # give it plenty of time to start
        while self.status.get() != 'Idle':
            time.sleep(.1)

    def load_sample(self, sample_number, sample_geometry=None):
        if self.current_sample_number.get() != 0:
            raise RuntimeError("Sample %d is already loaded." % self.current_sample_number.get())
        print('Moving theta to load position')
        self.theta.move(self.TH_POS[sample_geometry]['load'], wait=True)
        set_and_wait(self.sample_number, sample_number)
        set_and_wait(self.load_cmd, 1)
        print('Executing load command')
        self.execute_cmd.put(1)
        self._poll_until_idle()
        print('Moving theta to measure position')
        self.theta.move(self.TH_POS[sample_geometry]['measure'], wait=True)
        # Stash the current sample geometry for reference when we unload.
        self._current_sample_geometry = sample_geometry

    def unload_sample(self):
        if self.current_sample_number.get() == 0:
            # there is nothing to do
            return
        print('Moving theta to unload position')
        self.theta.move(self.TH_POS[self._current_sample_geometry]['load'], wait=True)
        print('Executing unload command')
        set_and_wait(self.unload_cmd, 1)
        self.execute_cmd.put(1)
        self._poll_until_idle()
        self._current_sample_geometry = None

    def stop(self):
        self.theta.stop()
        super().stop()
        

from bluesky.plans import abs_set, pchain, open_run, close_run
from bluesky import Msg


# Define custom commands for sample loading/unloading.

@asyncio.coroutine
def _load_sample(msg):
    msg.obj.load_sample(*msg.args, **msg.kwargs)


@asyncio.coroutine
def _unload_sample(msg):
    msg.obj.unload_sample(*msg.args, **msg.kwargs)


# Register these custom command with the RunEngine.

RE.register_command('load_sample', _load_sample)
RE.register_command('unload_sample', _unload_sample)


# For convenience, define short plans the use these custom commands.

def load_sample(position, geometry=None):
    # TODO: I think this can be simpler.
    return (yield from single_gen(Msg('load_sample', robot, position, geometry)))

def unload_sample():
    # TODO: I think this can be simpler.
    return (yield from single_gen(Msg('unload_sample', robot)))


# These are usable bluesky plans.

def robot_wrapper(plan, sample):
    """Wrap a plan in load/unload messages.

    Parameters
    ----------
    plan : a bluesky plan
    sample : dict
        must contain 'position'; optionally also 'geometry'

    Example
    -------
    >>> plan = count([pe1c])
    >>> new_plan = robot_wrapper(plan, {'position': 1})
    """
    yield from load_sample(sample['position'], sample.get('geometry', None))
    yield from plan
    yield from unload_sample()


def ct(sample, exposure):
    """
    Capture how many exposures are needed to get a total exposure
    of the given value, and sum those into one file before saving.
    """
    pe1c.images_per_set.put(1)
    pe1c.number_of_sets.put(1)
    plan = subs_wrapper(count([pe1c], num=1), LiveTable([]))
    # plan = robot_wrapper(plan, sample)
    yield from plan


def tseries(sample, exposure, num):
    """
    Capture how ever many exposures are needed to get a total exposure
    of the given value, and divide those into files of 'num' exposures
    each, summed.
    """
    if pe1c.cam.acquire_time.get() != 0.1:
        raise RuntimeError("We expect pe1c.cam.acquire_time to be 0.1")
    pe1c.images_per_set.put(num)
    pe1c.number_of_sets.put(exposure // num)
    plan = subs_wrapper(count([pe1c], num=1), LiveTable([]))
    i# plan = robot_wrapper(plan, sample)
    yield from plan


def Tramp(sample, exposure, start, stop, step):
    Tpoints = np.arange(start, stop, step)
    plan = subs_wrapper(list_scan([pec1], cs700, points), LiveTable([cs700]))
    # plan = robot_wrapper(plan, sample)
    yield from plan


# Define list of sample info.
samples = [{'position': 1, 'geometry': 'plate', 'sample_name': 'stuff'},
           {'position': 2, 'geometry': 'capillary', 'sample_name': 'other_stuff'}]

# master_plan = pchain(plan(sample) for sample in samples)

robot = Robot('XF:28IDC-ES:1{SM}', theta=th)

# old RobotPositioner code is .ipython/profile_2015_collection/startup/robot.py
