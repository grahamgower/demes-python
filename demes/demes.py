import typing
from typing import List, Union, Optional, Dict
import itertools
import math
import numbers
import copy
import operator
import warnings

import attr

Number = Union[int, float]
ID = str
Time = Number
Size = Number
Rate = float
Proportion = float

_ISCLOSE_REL_TOL = 1e-9
_ISCLOSE_ABS_TOL = 1e-12

# Validator functions.


def int_or_float(self, attribute, value):
    if (
        not isinstance(value, numbers.Real) and not hasattr(value, "__float__")
    ) or value != value:  # type-agnostic test for NaN
        raise TypeError(f"{attribute.name} must be a number")


def positive(self, attribute, value):
    if value <= 0:
        raise ValueError(f"{attribute.name} must be greater than zero")


def non_negative(self, attribute, value):
    if value < 0:
        raise ValueError(f"{attribute.name} must be non-negative")


def finite(self, attribute, value):
    if math.isinf(value):
        raise ValueError(f"{attribute.name} must be finite")


def unit_interval(self, attribute, value):
    if not (0 <= value <= 1):
        raise ValueError(f"must have 0 <= {attribute.name} <= 1")


def nonzero_len(self, attribute, value):
    if len(value) == 0:
        if isinstance(value, str):
            raise ValueError(f"{attribute.name} must be a non-empty string")
        else:
            raise ValueError(f"{attribute.name} must have non-zero length")


def valid_deme_id(self, attribute, value):
    if not value.isidentifier():
        raise ValueError(
            "Invalid deme ID `{self.id}`. IDs must be valid python identifiers. "
            "We recommend choosing a deme ID that starts with a letter or "
            "underscore, and is followed by one or more letters, numbers, "
            "or underscores."
        )


def isclose(
    a: Optional[Number],
    b: Optional[Number],
    *,
    rel_tol=_ISCLOSE_REL_TOL,
    abs_tol=_ISCLOSE_ABS_TOL,
) -> bool:
    """
    Wrapper around math.isclose() that handles None.
    """
    if None in (a, b):
        return (a,) == (b,)
    else:
        return math.isclose(
            typing.cast(float, a),
            typing.cast(float, b),
            rel_tol=rel_tol,
            abs_tol=abs_tol,
        )


def isclose_deme_proportions(
    a_ids: List[ID],
    a_proportions: List[Proportion],
    b_ids: List[ID],
    b_proportions: List[Proportion],
    *,
    rel_tol=_ISCLOSE_REL_TOL,
    abs_tol=_ISCLOSE_ABS_TOL,
) -> bool:
    """
    Returns true if (a_ids, a_proportions) and (b_ids, b_proportions)
    are semantically equivalent. The order of ids is ignored, and proportions
    are checked for numerical closeness.
    """
    if len(a_ids) != len(b_ids) or len(a_proportions) != len(b_proportions):
        return False
    a = sorted(zip(a_ids, a_proportions), key=operator.itemgetter(0))
    b = sorted(zip(b_ids, b_proportions), key=operator.itemgetter(0))
    for (a_id, a_proportion), (b_id, b_proportion) in zip(a, b):
        if a_id != b_id or not isclose(
            a_proportion, b_proportion, rel_tol=rel_tol, abs_tol=abs_tol
        ):
            return False
    return True


@attr.s(auto_attribs=True, kw_only=True)
class Epoch:
    """
    Population size parameters for a deme in a specified time period.
    Times follow the forwards-in-time convention (time values increase
    from the present towards the past). The start time of the epoch is
    the more ancient time, and the end time is more recent, so that the
    start time must be greater than the end time

    :ivar start_time: The start time of the epoch.
    :ivar end_time: The end time of the epoch (must be specified).
    :ivar initial_size: Population size at ``start_time``.
    :ivar final_size: Population size at ``end_time``.
        If ``initial_size != final_size``, the population size changes
        monotonically between the start and end times.
    :ivar size_function: The size change function. Common options are constant,
        exponential, or linear, though any string is valid. Warning: downstream
        simulators might not understand the size_function provided.
    :ivar selfing_rate: An optional selfing rate for this epoch.
    :ivar cloning_rate: An optional cloning rate for this epoch.
    """

    start_time: Optional[Time] = attr.ib(
        default=None,
        validator=attr.validators.optional([int_or_float, non_negative]),
    )
    end_time: Optional[Time] = attr.ib(
        default=None,
        validator=attr.validators.optional([int_or_float, non_negative, finite]),
    )
    initial_size: Optional[Size] = attr.ib(
        default=None,
        validator=attr.validators.optional([int_or_float, positive, finite]),
    )
    final_size: Optional[Size] = attr.ib(
        default=None,
        validator=attr.validators.optional([int_or_float, positive, finite]),
    )
    size_function: Optional[str] = attr.ib(
        default=None,
        validator=attr.validators.optional(
            [attr.validators.instance_of(str), nonzero_len]
        ),
    )
    selfing_rate: Optional[Proportion] = attr.ib(
        default=None,
        validator=attr.validators.optional([int_or_float, unit_interval]),
    )
    cloning_rate: Optional[Proportion] = attr.ib(
        default=None,
        validator=attr.validators.optional([int_or_float, unit_interval]),
    )

    def __attrs_post_init__(self):
        if self.initial_size is None and self.final_size is None:
            raise ValueError("must set either initial_size or final_size")
        if (
            self.start_time is not None
            and self.end_time is not None
            and self.start_time <= self.end_time
        ):
            raise ValueError("must have start_time > end_time")
        if (
            self.start_time is not None
            and self.initial_size is not None
            and self.final_size is not None
        ):
            if math.isinf(self.start_time) and self.initial_size != self.final_size:
                raise ValueError("if start time is inf, must be a constant size epoch")
        if (
            self.size_function == "constant"
            and self.initial_size is not None
            and self.final_size is not None
            and self.initial_size != self.final_size
        ):
            raise ValueError(
                "initial_size != final_size, but size_function is constant"
            )

    @property
    def time_span(self):
        """
        The time span of the epoch.
        """
        return self.start_time - self.end_time

    def assert_close(
        self,
        other,
        *,
        rel_tol=_ISCLOSE_REL_TOL,
        abs_tol=_ISCLOSE_ABS_TOL,
    ) -> bool:
        """
        Returns true if the epoch and ``other`` epoch implement essentially
        the same epoch and raises AssertionError otherwise.
        Compares values of the following attributes:
        ``start_time``, ``end_time``, ``initial_size``, ``final_size``,
        ``size_function``, ``selfing_rate``, ``cloning_rate``.

        :param other: The epoch to compare against.
        :type other: :class:`.Epoch`
        :param ret_tol: The relative tolerance permitted for numerical
                        comparisons. See documentation for :func:`math.isclose`
        :type ret_tol: float
        :param abs_tol: The absolute tolerance permitted for numerical
                        comparisons. See documentation for :func:`math.isclose`.
        :type abs_tol: float

        :return: True if the two epochs are equivalent, raises AssertionError\
                 otherwise.
        :rtype: bool
        """
        assert (
            self.__class__ is other.__class__
        ), f"Failed as other epoch is not instance of {self.__class__} type."
        assert isclose(
            self.start_time, other.start_time, rel_tol=rel_tol, abs_tol=abs_tol
        ), f"Failed for start_time {self.start_time} != {other.start_time} (other)."
        assert isclose(
            self.end_time, other.end_time, rel_tol=rel_tol, abs_tol=abs_tol
        ), f"Failed for end_time {self.end_time} != {other.end_time} (other)."
        assert isclose(
            self.initial_size, other.initial_size, rel_tol=rel_tol, abs_tol=abs_tol
        ), (
            f"Failed for initial_size "
            f"{self.initial_size} != {other.initial_size} (other)."
        )
        assert isclose(
            self.final_size, other.final_size, rel_tol=rel_tol, abs_tol=abs_tol
        ), f"Failed for final_size {self.final_size} != {other.final_size} (other)."
        assert self.size_function == other.size_function
        assert isclose(
            self.selfing_rate, other.selfing_rate, rel_tol=rel_tol, abs_tol=abs_tol
        ), (
            f"Failed for selfing_rate "
            f"{self.selfing_rate} != {other.selfing_rate} (other)."
        )
        assert isclose(
            self.cloning_rate, other.cloning_rate, rel_tol=rel_tol, abs_tol=abs_tol
        ), (
            f"Failed for cloning_rate "
            f"{self.cloning_rate} != {other.cloning_rate} (other)."
        )
        return True

    def isclose(
        self,
        other,
        *,
        rel_tol=_ISCLOSE_REL_TOL,
        abs_tol=_ISCLOSE_ABS_TOL,
    ) -> bool:
        """
        Returns true if the epoch and ``other`` epoch implement essentially
        the same epoch. For more information see :meth:`assert_close`.

        :param other: The epoch to compare against.
        :type other: :class:`.Epoch`
        :param ret_tol: The relative tolerance permitted for numerical
                        comparisons. See documentation for :func:`math.isclose`
        :type ret_tol: float
        :param abs_tol: The absolute tolerance permitted for numerical
                        comparisons. See documentation for :func:`math.isclose`.
        :type abs_tol: float


        :return: True if the two epochs are equivalent, False otherwise.
        :rtype: bool
        """
        try:
            self.assert_close(other, rel_tol=rel_tol, abs_tol=abs_tol)
            return True
        except AssertionError:
            return False


@attr.s(auto_attribs=True, kw_only=True)
class Migration:
    """
    Parameters for continuous migration from one deme to another.
    Source and destination demes follow the forwards-in-time convention,
    of migrations born in the source deme having children in the dest
    deme.

    :ivar source: The source deme.
    :ivar dest: The destination deme.
    :ivar start_time: The time at which the migration rate becomes activate.
    :ivar end_time: The time at which the migration rate is deactivated.
    :ivar rate: The rate of migration. Set to zero to disable migrations after
        the given time.
    """

    source: ID = attr.ib(validator=[attr.validators.instance_of(str), valid_deme_id])
    dest: ID = attr.ib(validator=[attr.validators.instance_of(str), valid_deme_id])
    start_time: Time = attr.ib(validator=[int_or_float, non_negative])
    end_time: Time = attr.ib(validator=[int_or_float, non_negative, finite])
    rate: Rate = attr.ib(validator=[int_or_float, non_negative, finite])

    def __attrs_post_init__(self):
        if self.source == self.dest:
            raise ValueError("source and dest cannot be the same deme")

    def assert_close(
        self,
        other,
        *,
        rel_tol=_ISCLOSE_REL_TOL,
        abs_tol=_ISCLOSE_ABS_TOL,
    ) -> bool:
        """
        Returns true if the migration is equal to the ``other`` migration and
        raises AssertionError otherwise.
        Compares values of the following attributes:
        ``source``, ``dest``, ``start_time``, ``end_time``, ``rate``.

        :param other: The migration to compare against.
        :type other: :class:`.Migration`
        :param ret_tol: The relative tolerance permitted for numerical
                        comparisons. See documentation for :func:`math.isclose`
        :type ret_tol: float
        :param abs_tol: The absolute tolerance permitted for numerical
                        comparisons. See documentation for :func:`math.isclose`.
        :type abs_tol: float

        :return: True if the two migrations are equivalent, raises\
                 AssertionError otherwise.
        :rtype: bool
        """
        assert (
            self.__class__ is other.__class__
        ), f"Failed as other migration is not instance of {self.__class__} type."
        assert self.source == other.source
        assert self.dest == other.dest
        assert isclose(
            self.start_time, other.start_time, rel_tol=rel_tol, abs_tol=abs_tol
        ), f"Failed for start_time {self.start_time} != {other.start_time} (other)."
        assert isclose(
            self.end_time, other.end_time, rel_tol=rel_tol, abs_tol=abs_tol
        ), f"Failed for end_time {self.end_time} != {other.end_time} (other)."
        assert isclose(
            self.rate, other.rate, rel_tol=rel_tol, abs_tol=abs_tol
        ), f"Failed for rate {self.rate} != {other.rate} (other)."
        return True

    def isclose(
        self,
        other,
        *,
        rel_tol=_ISCLOSE_REL_TOL,
        abs_tol=_ISCLOSE_ABS_TOL,
    ) -> bool:
        """
        Returns true if the migration is equal to the ``other`` migration.
        For more information see :meth:`assert_close`.

        :param other: The migration to compare against.
        :type other: :class:`.Migration`
        :param ret_tol: The relative tolerance permitted for numerical
                        comparisons. See documentation for :func:`math.isclose`
        :type ret_tol: float
        :param abs_tol: The absolute tolerance permitted for numerical
                        comparisons. See documentation for :func:`math.isclose`.
        :type abs_tol: float

        :return: True if the two epochs are equivalent, False otherwise.
        :rtype: bool

        """
        try:
            self.assert_close(other, rel_tol=rel_tol, abs_tol=abs_tol)
            return True
        except AssertionError:
            return False


@attr.s(auto_attribs=True, kw_only=True)
class Pulse:
    """
    Parameters for a pulse of migration from one deme to another.
    Source and destination demes follow the forwards-in-time convention,
    of migrations born in the source deme having children in the dest
    deme.

    :ivar source: The source deme.
    :ivar dest: The destination deme.
    :ivar time: The time of migration.
    :ivar proportion: At the instant after migration, this is the proportion
        of individuals in the destination deme made up of individuals from
        the source deme.
    """

    source: ID = attr.ib(validator=[attr.validators.instance_of(str), valid_deme_id])
    dest: ID = attr.ib(validator=[attr.validators.instance_of(str), valid_deme_id])
    time: Time = attr.ib(validator=[int_or_float, non_negative, finite])
    proportion: Proportion = attr.ib(validator=[int_or_float, unit_interval])

    def __attrs_post_init__(self):
        if self.source == self.dest:
            raise ValueError("source and dest cannot be the same deme")

    def assert_close(
        self,
        other,
        *,
        rel_tol=_ISCLOSE_REL_TOL,
        abs_tol=_ISCLOSE_ABS_TOL,
    ) -> bool:
        """
        Returns true if the pulse is equal to the ``other`` pulse and raises
        AssertionError otherwise.
        Compares values of the following attributes:
        ``source``, ``dest``, ``time``, ``proportion``.

        :param other: The pulse to compare against.
        :type other: :class:`.Pulse`
        :param ret_tol: The relative tolerance permitted for numerical
                        comparisons. See documentation for :func:`math.isclose`
        :type ret_tol: float
        :param abs_tol: The absolute tolerance permitted for numerical
                        comparisons. See documentation for :func:`math.isclose`.
        :type abs_tol: float

        :return: True if the two pulses are equivalent, raises AssertionError\
                 otherwise.
        :rtype: bool
        """
        assert (
            self.__class__ is other.__class__
        ), f"Failed as other pulse is not instance of {self.__class__} type."
        assert self.source == other.source
        assert self.dest == other.dest
        assert isclose(
            self.time, other.time, rel_tol=rel_tol, abs_tol=abs_tol
        ), f"Failed for time {self.time} != {other.time} (other)."
        assert isclose(
            self.proportion, other.proportion, rel_tol=rel_tol, abs_tol=abs_tol
        ), f"Failed for proportion {self.proportion} != {other.proportion} (other)."
        return True

    def isclose(
        self,
        other,
        *,
        rel_tol=_ISCLOSE_REL_TOL,
        abs_tol=_ISCLOSE_ABS_TOL,
    ) -> bool:
        """
        Returns true if the pulse is equal to the ``other`` pulse.
        For more information see :meth:`assert_close`.

        :param other: The pulse to compare against.
        :type other: :class:`.Pulse`
        :param ret_tol: The relative tolerance permitted for numerical
                        comparisons. See documentation for :func:`math.isclose`
        :type ret_tol: float
        :param abs_tol: The absolute tolerance permitted for numerical
                        comparisons. See documentation for :func:`math.isclose`.
        :type abs_tol: float

        :return: True if the two pulses are equivalent, False otherwise.
        :rtype: bool

        """
        try:
            self.assert_close(other, rel_tol=rel_tol, abs_tol=abs_tol)
            return True
        except AssertionError:
            return False


@attr.s(auto_attribs=True, kw_only=True)
class Split:
    """
    Parameters for a split event, in which a deme ends at a given time and
    contributes ancestry to an arbitrary number of descendant demes. Note
    that there could be just a single descendant deme, in which case ``split``
    is a bit of a misnomer...

    :ivar parent: The parental deme.
    :ivar children: A list of descendant demes.
    :ivar time: The split time.
    """

    parent: ID = attr.ib(validator=[attr.validators.instance_of(str), valid_deme_id])
    children: List[ID] = attr.ib(
        validator=attr.validators.and_(
            attr.validators.deep_iterable(
                member_validator=attr.validators.and_(
                    attr.validators.instance_of(str), valid_deme_id
                ),
                iterable_validator=attr.validators.instance_of(list),
            ),
            nonzero_len,
        )
    )
    time: Time = attr.ib(validator=[int_or_float, non_negative, finite])

    def __attrs_post_init__(self):
        if self.parent in self.children:
            raise ValueError("child and parent cannot be the same deme")
        if len(set(self.children)) != len(self.children):
            raise ValueError("cannot repeat children in split")

    def assert_close(
        self,
        other,
        *,
        rel_tol=_ISCLOSE_REL_TOL,
        abs_tol=_ISCLOSE_ABS_TOL,
        raise_ex=False,
    ) -> bool:
        """
        Returns true if the split is equal to the ``other`` split and raises
        AssertionError otherwise.
        Compares values of the following attributes:
        ``parent``, ``children``, ``time``.

        :param other: The split to compare against.
        :type other: :class:`.Split`
        :param ret_tol: The relative tolerance permitted for numerical
                        comparisons. See documentation for :func:`math.isclose`
        :type ret_tol: float
        :param abs_tol: The absolute tolerance permitted for numerical
                        comparisons. See documentation for :func:`math.isclose`.
        :type abs_tol: float

        :return: True if the two splits are equivalent, raises AssertionError\
                 otherwise.
        :rtype: bool
        """
        assert (
            self.__class__ is other.__class__
        ), f"Failed as other split is not instance of {self.__class__} type."
        assert self.parent == other.parent
        assert sorted(self.children) == sorted(other.children)
        assert isclose(
            self.time, other.time, rel_tol=rel_tol, abs_tol=abs_tol
        ), f"Failed for time {self.time} != {other.time} (other)."
        return True

    def isclose(
        self,
        other,
        *,
        rel_tol=_ISCLOSE_REL_TOL,
        abs_tol=_ISCLOSE_ABS_TOL,
    ) -> bool:
        """
        Returns true if the split is equal to the ``other`` split.
        Compares values of the following attributes:
        ``parent``, ``children``, ``time``.

        :param other: The split to compare against.
        :type other: :class:`.Split`
        :param ret_tol: The relative tolerance permitted for numerical
                        comparisons. See documentation for :func:`math.isclose`
        :type ret_tol: float
        :param abs_tol: The absolute tolerance permitted for numerical
                        comparisons. See documentation for :func:`math.isclose`.
        :type abs_tol: float
        :param raise_ex: Determines if exception (ValueError) should be raised
                         when splits are not close. The error will contain
                         information about attributes that are not equal.
        :type raise_ex: bool

        :return: True if the two splits are equivalent, False otherwise.
        :rtype: bool
        """
        try:
            self.assert_close(other, rel_tol=rel_tol, abs_tol=abs_tol)
            return True
        except AssertionError:
            return False


@attr.s(auto_attribs=True, kw_only=True)
class Branch:
    """
    Parameters for a branch event, where a new deme branches off from a parental
    deme. The parental deme need not end at that time.

    :ivar parent: The parental deme.
    :ivar child: The descendant deme.
    :ivar time: The branch time.
    """

    parent: ID = attr.ib(validator=[attr.validators.instance_of(str), valid_deme_id])
    child: ID = attr.ib(validator=[attr.validators.instance_of(str), valid_deme_id])
    time: Time = attr.ib(validator=[int_or_float, non_negative, finite])

    def __attrs_post_init__(self):
        if self.child == self.parent:
            raise ValueError("child and parent cannot be the same deme")

    def assert_close(
        self,
        other,
        *,
        rel_tol=_ISCLOSE_REL_TOL,
        abs_tol=_ISCLOSE_ABS_TOL,
    ) -> bool:
        """
        Returns true if the branch is equal to the ``other`` branch and raises
        AssertionError otherwise.
        Compares values of the following attributes:
        ``parent``, ``child``, ``time``.

        :param other: The branch to compare against.
        :type other: :class:`.Branch`
        :param ret_tol: The relative tolerance permitted for numerical
                        comparisons. See documentation for :func:`math.isclose`
        :type ret_tol: float
        :param abs_tol: The absolute tolerance permitted for numerical
                        comparisons. See documentation for :func:`math.isclose`.
        :type abs_tol: float
        :param raise_ex: Determines if exception (ValueError) should be raised
                         when branches are not close. The error will contain
                         information about attributes that are not equal.
        :type raise_ex: bool

        :return: True if the two branches are equivalent, raises\
                 AssertionError otherwise.
        :rtype: bool
        """
        assert (
            self.__class__ is other.__class__
        ), f"failed as other branch is not instance of {self.__class__} type."
        assert self.parent == other.parent
        assert sorted(self.child) == sorted(other.child)
        assert isclose(
            self.time, other.time, rel_tol=rel_tol, abs_tol=abs_tol
        ), f"Failed for time {self.time} != {other.time} (other)."
        return True

    def isclose(
        self,
        other,
        *,
        rel_tol=_ISCLOSE_REL_TOL,
        abs_tol=_ISCLOSE_ABS_TOL,
    ) -> bool:
        """
        Returns true if the branch is equal to the ``other`` branch.
        For more information see :meth:`assert_close`.

        :param other: The branch to compare against.
        :type other: :class:`.Branch`
        :param ret_tol: The relative tolerance permitted for numerical
                        comparisons. See documentation for :func:`math.isclose`
        :type ret_tol: float
        :param abs_tol: The absolute tolerance permitted for numerical
                        comparisons. See documentation for :func:`math.isclose`.
        :type abs_tol: float

        :return: True if the two branches are equivalent, False otherwise.
        :rtype: bool

        """
        try:
            self.assert_close(other, rel_tol=rel_tol, abs_tol=abs_tol)
            return True
        except AssertionError:
            return False


@attr.s(auto_attribs=True, kw_only=True)
class Merge:
    """
    Parameters for a merge event, in which two or more demes end at some time and
    contribute to a descendant deme.

    :ivar parents: A list of parental demes.
    :ivar proportions: A list of ancestry proportions, in order of `parents`.
    :ivar child: The descendant deme.
    :ivar time: The merge time.
    """

    parents: List[ID] = attr.ib(
        validator=attr.validators.deep_iterable(
            member_validator=attr.validators.and_(
                attr.validators.instance_of(str), valid_deme_id
            ),
            iterable_validator=attr.validators.instance_of(list),
        )
    )
    proportions: List[Proportion] = attr.ib(
        validator=attr.validators.deep_iterable(
            member_validator=int_or_float,
            iterable_validator=attr.validators.instance_of(list),
        )
    )
    child: ID = attr.ib(validator=[attr.validators.instance_of(str), valid_deme_id])
    time: Time = attr.ib(validator=[int_or_float, non_negative, finite])

    @proportions.validator
    def _check_proportions(self, attribute, _value):
        if len(self.proportions) > 0 and not math.isclose(sum(self.proportions), 1.0):
            raise ValueError("proportions must sum to 1.0")
        for proportion in self.proportions:
            unit_interval(self, attribute, proportion)
            positive(self, attribute, proportion)

    def __attrs_post_init__(self):
        if len(self.parents) < 2:
            raise ValueError("merge must involve at least two ancestors")
        if len(self.parents) != len(self.proportions):
            raise ValueError("parents and proportions must have same length")
        if self.child in self.parents:
            raise ValueError("merged deme cannot be its own ancestor")
        if len(set(self.parents)) != len(self.parents):
            raise ValueError("cannot repeat parents in merge")

    def assert_close(
        self,
        other,
        *,
        rel_tol=_ISCLOSE_REL_TOL,
        abs_tol=_ISCLOSE_ABS_TOL,
    ) -> bool:
        """
        Returns true if the merge is equal to the ``other`` merge and raises
        AssertionError otherwise.
        Compares values of the following attributes:
        ``parents``, ``proportions``, ``child``, ``time``.

        :param other: The merge to compare against.
        :type other: :class:`.Merge`
        :param ret_tol: The relative tolerance permitted for numerical
                        comparisons. See documentation for :func:`math.isclose`
        :type ret_tol: float
        :param abs_tol: The absolute tolerance permitted for numerical
                        comparisons. See documentation for :func:`math.isclose`.
        :type abs_tol: float

        :return: True if the two merges are equivalent, raises AssertionError\
                 otherwise.
        :rtype: bool
        """
        assert (
            self.__class__ is other.__class__
        ), f"Failed as other merge is not instance of {self.__class__} type."
        assert isclose_deme_proportions(
            self.parents,
            self.proportions,
            other.parents,
            other.proportions,
            rel_tol=rel_tol,
            abs_tol=abs_tol,
        ), (
            f"Parents or corresponding proportions are different: "
            f"parents: {self.parents}, {other.parents} (other), "
            f"proportions: {self.proportions}, {other.proportions} (other)."
        )
        assert sorted(self.child) == sorted(other.child)
        assert isclose(
            self.time, other.time, rel_tol=rel_tol, abs_tol=abs_tol
        ), f"Failed for time {self.time} != {other.time} (other)."
        return True

    def isclose(
        self,
        other,
        *,
        rel_tol=_ISCLOSE_REL_TOL,
        abs_tol=_ISCLOSE_ABS_TOL,
    ) -> bool:
        """
        Returns true if the merge is equal to the ``other`` merge.
        For more information see :meth:`assert_close`.

        :param other: The merge to compare against.
        :type other: :class:`.Merge`
        :param ret_tol: The relative tolerance permitted for numerical
                        comparisons. See documentation for :func:`math.isclose`
        :type ret_tol: float
        :param abs_tol: The absolute tolerance permitted for numerical
                        comparisons. See documentation for :func:`math.isclose`.
        :type abs_tol: float

        :return: True if the two merges are equivalent, False otherwise.
        :rtype: bool

        """
        try:
            self.assert_close(other, rel_tol=rel_tol, abs_tol=abs_tol)
            return True
        except AssertionError:
            return False


@attr.s(auto_attribs=True, kw_only=True)
class Admix:
    """
    Parameters for an admixture event, where two or more demes contribute ancestry
    to a new deme.

    :ivar parents: A list of source demes.
    :ivar proportions: A list of ancestry proportions, in order of `parents`.
    :ivar child: The admixed deme.
    :ivar time: The admixture time.
    """

    parents: List[ID] = attr.ib(
        validator=attr.validators.deep_iterable(
            member_validator=attr.validators.and_(
                attr.validators.instance_of(str), valid_deme_id
            ),
            iterable_validator=attr.validators.instance_of(list),
        )
    )
    proportions: List[Proportion] = attr.ib(
        validator=attr.validators.deep_iterable(
            member_validator=int_or_float,
            iterable_validator=attr.validators.instance_of(list),
        )
    )
    child: ID = attr.ib(validator=[attr.validators.instance_of(str), valid_deme_id])
    time: Time = attr.ib(validator=[int_or_float, non_negative, finite])

    @proportions.validator
    def _check_proportions(self, attribute, _value):
        if len(self.proportions) > 0 and not math.isclose(sum(self.proportions), 1.0):
            raise ValueError("proportions must sum to 1.0")
        for proportion in self.proportions:
            unit_interval(self, attribute, proportion)
            positive(self, attribute, proportion)

    def __attrs_post_init__(self):
        if len(self.parents) < 2:
            raise ValueError("admixture must involve at least two ancestors")
        if len(self.parents) != len(self.proportions):
            raise ValueError("parents and proportions must have same length")
        if self.child in self.parents:
            raise ValueError("admixed deme cannot be its own ancestor")
        if len(set(self.parents)) != len(self.parents):
            raise ValueError("cannot repeat parents in admixure")

    def assert_close(
        self,
        other,
        *,
        rel_tol=_ISCLOSE_REL_TOL,
        abs_tol=_ISCLOSE_ABS_TOL,
        raise_ex=False,
    ) -> bool:
        """
        Returns true if the admixture is equal to the ``other`` admixture and
        raises AssertionError otherwise.
        Compares values of the following attributes:
        ``parents``, ``proportions``, ``child``, ``time``.

        :param other: The admixture to compare against.
        :type other: :class:`.Admix`
        :param ret_tol: The relative tolerance permitted for numerical
                        comparisons. See documentation for :func:`math.isclose`
        :type ret_tol: float
        :param abs_tol: The absolute tolerance permitted for numerical
                        comparisons. See documentation for :func:`math.isclose`.
        :type abs_tol: float
        :param raise_ex: Determines if exception (ValueError) should be raised
                         when admixtures are not close. The error will contain
                         information about attributes that are not equal.
        :type raise_ex: bool

        :return: True if the two admixtures are equivalent, raises\
                 AssertionError otherwise.
        :rtype: bool
        """
        assert (
            self.__class__ is other.__class__
        ), f"Failed as other admixture is not instance of {self.__class__} type."
        assert isclose_deme_proportions(
            self.parents,
            self.proportions,
            other.parents,
            other.proportions,
            rel_tol=rel_tol,
            abs_tol=abs_tol,
        ), (
            f"Parents or corresponding proportions are different: "
            f"parents: {self.parents}, {other.parents} (other), "
            f"proportions: {self.proportions}, {other.proportions} (other)."
        )
        assert sorted(self.child) == sorted(other.child)
        assert isclose(
            self.time,
            other.time,
            rel_tol=rel_tol,
            abs_tol=abs_tol,
        ), f"Failed for time {self.time} != {other.time} (other)."
        return True

    def isclose(
        self,
        other,
        *,
        rel_tol=_ISCLOSE_REL_TOL,
        abs_tol=_ISCLOSE_ABS_TOL,
    ) -> bool:
        """
        Returns true if the admixture is equal to the ``other`` admixture.
        For more information see :meth:`assert_close`.

        :param other: The admixture to compare against.
        :type other: :class:`.Admix`
        :param ret_tol: The relative tolerance permitted for numerical
                        comparisons. See documentation for :func:`math.isclose`
        :type ret_tol: float
        :param abs_tol: The absolute tolerance permitted for numerical
                        comparisons. See documentation for :func:`math.isclose`.
        :type abs_tol: float
        :param raise_ex: Determines if exception (ValueError) should be raised
                         when admixtures are not close. The error will contain
                         information about attributes that are not equal.
        :type raise_ex: bool

        :return: True if the two admixtures are equivalent, False otherwise.
        :rtype: bool
        """
        try:
            self.assert_close(other, rel_tol=rel_tol, abs_tol=abs_tol)
            return True
        except AssertionError:
            return False


@attr.s(auto_attribs=True, kw_only=True)
class Deme:
    """
    A collection of individuals that are exchangeable at any fixed time.
    This class is not intended to be instantiated directly. It is instead
    recommended to add demes to a :class:`.Graph` object using the
    :meth:`Graph.deme` method.

    :ivar str id: A string identifier for the deme.
    :ivar str description: A description of the deme. May be ``None``.
    :ivar ancestors: List of string identifiers for the deme's ancestors.
        This may be ``None``, indicating the deme has no ancestors.
    :vartype ancestors: list of str
    :ivar proportions: If ``ancestors`` is not ``None``, this indicates the
        proportions of ancestry from each ancestor. This list has the same
        length as ``ancestors``, and must sum to 1.
    :vartype proportions: list of float
    :ivar epochs: A list of epochs, which define the population size(s) of
        the deme. The deme must be created with all epochs listed.
    :vartype epochs: list of :class:`.Epoch`
    :ivar defaults: A dictionary of default attributes, such as cloning and
        selfing rates, that are inherited by epochs if those attributes are
        not specified in the epoch.
    :vartype defaults: dict
    """

    id: ID = attr.ib(validator=[attr.validators.instance_of(str), valid_deme_id])
    description: Optional[str] = attr.ib(
        validator=attr.validators.optional(
            [attr.validators.instance_of(str), nonzero_len]
        )
    )
    ancestors: List[ID] = attr.ib(
        validator=attr.validators.deep_iterable(
            member_validator=attr.validators.and_(
                attr.validators.instance_of(str), valid_deme_id
            ),
            iterable_validator=attr.validators.instance_of(list),
        )
    )
    proportions: List[Proportion] = attr.ib(
        validator=attr.validators.deep_iterable(
            member_validator=int_or_float,
            iterable_validator=attr.validators.instance_of(list),
        )
    )
    epochs: List[Epoch] = attr.ib(
        validator=attr.validators.deep_iterable(
            member_validator=attr.validators.instance_of(Epoch),
            iterable_validator=attr.validators.instance_of(list),
        )
    )
    defaults: dict = attr.ib()

    @ancestors.validator
    def _check_ancestors(self, _attribute, _value):
        if len(set(self.ancestors)) != len(self.ancestors):
            raise ValueError(f"duplicate ancestors in {self.ancestors}")
        if self.id in self.ancestors:
            raise ValueError(f"{self.id} cannot be its own ancestor")

    @proportions.validator
    def _check_proportions(self, attribute, _value):
        if len(self.proportions) > 0 and not math.isclose(sum(self.proportions), 1.0):
            raise ValueError("proportions must sum to 1.0")
        for proportion in self.proportions:
            unit_interval(self, attribute, proportion)
            positive(self, attribute, proportion)

    @epochs.validator
    def _check_epochs(self, _attribute, _value):
        # every deme must have at least one epoch
        if len(self.epochs) == 0:
            raise ValueError("Demes must be defined with at least one epoch")
        # check epoch times align
        for i, epoch in enumerate(self.epochs):
            if i > 0:
                if self.epochs[i - 1].end_time != epoch.start_time:
                    raise ValueError("Epoch start and end times must align")

    def __attrs_post_init__(self):
        # We check the lengths of ancestors and proportions match
        # after the validators have confirmed that these are indeed lists.
        if len(self.ancestors) != len(self.proportions):
            raise ValueError("ancestors and proportions must have same length")

    def assert_close(
        self,
        other,
        *,
        rel_tol=_ISCLOSE_REL_TOL,
        abs_tol=_ISCLOSE_ABS_TOL,
    ) -> bool:
        """
        Returns true if the deme is equal to the ``other`` deme and raises
        AssertionError otherwise.
        Compares values of the following objects:
        ``id``, ``ancestors``, ``proportions``, epochs.

        :param other: The deme to compare against.
        :type other: :class:`.Deme`
        :param ret_tol: The relative tolerance permitted for numerical
                        comparisons. See documentation for :func:`math.isclose`
        :type ret_tol: float
        :param abs_tol: The absolute tolerance permitted for numerical
                        comparisons. See documentation for :func:`math.isclose`.
        :type abs_tol: float

        :return: True if the two demes are equivalent, raises AssertionError\
                 otherwise.
        :rtype: bool
        """
        assert (
            self.__class__ is other.__class__
        ), f"Failed as other deme is not instance of {self.__class__} type."
        assert sorted(self.id) == sorted(other.id)
        assert isclose_deme_proportions(
            self.ancestors,
            self.proportions,
            other.ancestors,
            other.proportions,
            rel_tol=rel_tol,
            abs_tol=abs_tol,
        ), (
            f"Ancestors or corresponding proportions are different: "
            f"ancestors: {self.ancestors}, {other.ancestors} (other), "
            f"proportions: {self.proportions}, {other.proportions} (other)."
        )
        for i, (e1, e2) in enumerate(zip(self.epochs, other.epochs)):
            try:
                e1.assert_close(e2, rel_tol=rel_tol, abs_tol=abs_tol)
            except AssertionError as e:
                raise AssertionError(f"Failed for epochs (number {i})") from e
        return True

    def isclose(
        self,
        other,
        *,
        rel_tol=_ISCLOSE_REL_TOL,
        abs_tol=_ISCLOSE_ABS_TOL,
    ) -> bool:
        """
        Returns true if the deme is equal to the ``other`` deme.
        For more information see :meth:`assert_close`.

        :param other: The deme to compare against.
        :type other: :class:`.Deme`
        :param ret_tol: The relative tolerance permitted for numerical
                        comparisons. See documentation for :func:`math.isclose`
        :type ret_tol: float
        :param abs_tol: The absolute tolerance permitted for numerical
                        comparisons. See documentation for :func:`math.isclose`.
        :type abs_tol: float

        :return: True if the two demes are equivalent, False otherwise.
        :rtype: bool
        """
        try:
            self.assert_close(other, rel_tol=rel_tol, abs_tol=abs_tol)
            return True
        except AssertionError:
            return False

    @property
    def start_time(self):
        """
        The start time of the deme's existence.
        """
        return self.epochs[0].start_time

    @property
    def end_time(self):
        """
        The end time of the deme's existence.
        """
        return self.epochs[-1].end_time

    @property
    def time_span(self):
        """
        The time span over which the deme exists.
        """
        return self.start_time - self.end_time


@attr.s(auto_attribs=True, kw_only=True)
class Graph:
    """
    The Graph class provides a high-level API for constructing a demographic
    model. The methods on this class ensure validity of a  model at all stages
    of construction. They also allow omission of detail, when there is a single
    unambiguous interpretation (or a very sensible default). The semantics
    exactly match those for loading the ``yaml`` file, as the :func:`.load`
    function uses this API internally.

    :ivar str description: A human readable description of the demography.
    :ivar str time_units: The units of time used for the demography. This is
        commonly ``years`` or ``generations``, but can be any string.
        This field is intended to be useful for documenting a demography,
        but the actual value provided here should not be relied upon.
    :ivar float generation_time: The generation time of demes, in units given
        by the ``time_units`` parameter. Concretely, dividing all times
        by ``generation_time`` will convert the graph to have time
        units in generations.  If ``generation_time`` is ``None``, the units
        are assumed to be in generations already.
        See also: :meth:`.in_generations`.
    :ivar doi: If the graph describes a published demography, the DOI(s)
        should be be given here as a list.
    :vartype doi: list of str
    :ivar demes: A list of demes in the demography.
        Use :meth:`.deme` to add a deme.
    :vartype demes: list of :class:`.Deme`
    :ivar migrations: A list of continuous migrations for the demography.
        Use :meth:`migration` or :meth:`symmetric_migration` to add migrations.
    :vartype migrations: list of :class:`.Migration`
    :ivar pulses: A list of migration pulses for the demography.
        Use :meth:`pulse` to add a pulse.
    :vartype pulses: list of :class:`.Pulse`
    :ivar defaults: A dictionary of default attributes for demes and epochs.
    :vartype defaults: dict
    """

    description: str = attr.ib(
        validator=[attr.validators.instance_of(str), nonzero_len]
    )
    time_units: str = attr.ib(validator=[attr.validators.instance_of(str), nonzero_len])
    generation_time: Optional[Time] = attr.ib(
        default=None,
        validator=attr.validators.optional([int_or_float, positive, finite]),
    )
    doi: List[str] = attr.ib(
        factory=list,
        validator=attr.validators.deep_iterable(
            member_validator=attr.validators.and_(
                attr.validators.instance_of(str), nonzero_len
            ),
            iterable_validator=attr.validators.instance_of(list),
        ),
    )
    demes: List[Deme] = attr.ib(factory=list, init=False)
    migrations: List[Migration] = attr.ib(factory=list, init=False)
    pulses: List[Pulse] = attr.ib(factory=list, init=False)
    defaults: dict = attr.ib(default={})

    def __attrs_post_init__(self):
        self._deme_map: Dict[ID, Deme] = dict()

        if self.time_units != "generations" and self.generation_time is None:
            raise ValueError(
                'if time_units!="generations", generation_time must be specified'
            )

    def __getitem__(self, deme_id):
        """
        Return the :class:`.Deme` with the specified id.
        """
        return self._deme_map[deme_id]

    def __contains__(self, deme_id):
        """
        Check if the graph contains a deme with the specified id.
        """
        return deme_id in self._deme_map

    def assert_close(
        self,
        other,
        *,
        rel_tol=_ISCLOSE_REL_TOL,
        abs_tol=_ISCLOSE_ABS_TOL,
    ) -> bool:
        """
        Returns true if the graph and ``other`` implement essentially
        the same demographic model and raises AssertionError otherwise.
        Numerical values are compared using the
        :func:`math.isclose` function, from which this method takes its name.
        Furthermore, the following implementation details are ignored during
        the comparison:

            - The graphs' ``description`` and ``doi`` attributes.
            - The order in which ``migrations`` were specified.
            - The order in which admixture ``pulses`` were specified.
            - The order in which ``demes`` were specified.
            - The order in which a deme's ``ancestors`` were specified.
            - The ``selfing_rate`` and ``cloning_rate`` attributes of the deme
              graph, or of the demes (if any). Theses attributes are considered
              conveniences, and are propagated to the relevant demes'
              epochs. The ``selfing_rate`` and ``cloning_rate`` attributes of
              each epoch *are* evaluated for equality between the two models.

        :param other: The graph to compare against.
        :type other: :class:`.Graph`
        :param float rel_tol: The relative tolerance permitted for numerical
            comparisons. See documentation for :func:`math.isclose`.
        :param float abs_tol: The absolute tolerance permitted for numerical
            comparisons. See documentation for :func:`math.isclose`.
        :return: True if the two graphs implement the same model, raises\
                 AssertionError otherwise.
        :rtype: bool
        """

        def sorted_eq(aa, bb, *, rel_tol, abs_tol, name) -> bool:
            # Order-agnostic equality check.
            assert len(aa) == len(bb)
            for (a, b) in zip(sorted(aa), sorted(bb)):
                try:
                    a.assert_close(b, rel_tol=rel_tol, abs_tol=abs_tol)
                except AssertionError as e:
                    if isinstance(a, Deme) and isinstance(b, Deme):
                        raise AssertionError(
                            f"Failed for {name} {a.id} and {b.id}"
                        ) from e
                    raise AssertionError(f"Failed for {name}") from e
            return True

        assert (
            self.__class__ is other.__class__
        ), f"Failed as other graph is not instance of {self.__class__} type."
        assert self.time_units == other.time_units
        assert self.generation_time == other.generation_time
        return (
            sorted_eq(
                self.demes, other.demes, rel_tol=rel_tol, abs_tol=abs_tol, name="demes"
            )
            and sorted_eq(
                self.migrations,
                other.migrations,
                rel_tol=rel_tol,
                abs_tol=abs_tol,
                name="migrations",
            )
            and sorted_eq(
                self.pulses,
                other.pulses,
                rel_tol=rel_tol,
                abs_tol=abs_tol,
                name="pulses",
            )
        )

    def isclose(
        self,
        other,
        *,
        rel_tol=_ISCLOSE_REL_TOL,
        abs_tol=_ISCLOSE_ABS_TOL,
    ) -> bool:
        """
        Returns true if the graph and ``other`` implement essentially
        the same demographic model. Numerical values are compared using the
        :func:`math.isclose` function, from which this method takes its name.
        Furthermore, the following implementation details are ignored during
        the comparison:

            - The graphs' ``description`` and ``doi`` attributes.
            - The order in which ``migrations`` were specified.
            - The order in which admixture ``pulses`` were specified.
            - The order in which ``demes`` were specified.
            - The order in which a deme's ``ancestors`` were specified.
            - The ``selfing_rate`` and ``cloning_rate`` attributes of the deme
              graph, or of the demes (if any). Theses attributes are considered
              conveniences, and are propagated to the relevant demes'
              epochs. The ``selfing_rate`` and ``cloning_rate`` attributes of
              each epoch *are* evaluated for equality between the two models.

        :param other: The graph to compare against.
        :type other: :class:`.Graph`
        :param float rel_tol: The relative tolerance permitted for numerical
            comparisons. See documentation for :func:`math.isclose`.
        :param float abs_tol: The absolute tolerance permitted for numerical
            comparisons. See documentation for :func:`math.isclose`.
        :return: True if the two graphs implement the same model, False otherwise.
        :rtype: bool
        """
        try:
            self.assert_close(other, rel_tol=rel_tol, abs_tol=abs_tol)
            return True
        except AssertionError:
            return False

    def deme(
        self,
        id,
        *,
        description=None,
        ancestors=None,
        proportions=None,
        epochs=None,
        start_time=None,
        end_time=None,
        initial_size=None,
        final_size=None,
        defaults={},
    ) -> Deme:
        """
        Add a deme to the graph, with lifetime ``(start_time, end_time]``.

        :param str id: A string identifier for the deme.
        :param ancestors: List of string identifiers for the deme's ancestors.
            This may be ``None``, indicating the deme has no ancestors.
            If the deme has multiple ancestors, the ``proportions`` parameter
            must also be provided.
        :type ancestors: list of str
        :param list proportions: A list of ancestry proportions for ``ancestors``.
            This list has the same length as ``ancestors``, and must sum to ``1.0``.
            May be omitted if the deme has only one, or zero, ancestors.
        :type proportions: list of float
        :param float start_time: The time at which this deme begins existing,
            in units of ``time_units`` before the present.

            - If the deme has zero ancestors, and ``start_time`` is not specified,
              the start time will be set to ``inf``.
            - If the deme has one ancestor, and ``start_time`` is not specified,
              the ``start_time`` will be set to the ancestor's ``end_time``.
            - If the deme has multiple ancestors, the ``start_time`` must be
              provided.

        :param float end_time: The time at which this deme stops existing,
            in units of ``time_units`` before the present.
            If not specified, defaults to ``0.0`` (the present).
        :param initial_size: The initial population size of the deme.
            This must be provided.
        :param final_size: The final population size of the deme. If ``None``,
            the deme has a constant ``initial_size`` population size.
        :param epochs: Epochs that define population sizes, selfing rates, and
            cloning rates, for the deme over various time periods.
            If not specified, a single epoch will be created for the deme that
            spans from ``start_time`` to ``end_time``, using the ``initial_size``,
            ``final_size``, ``selfing_rate`` and ``cloning_rate`` provided.
        :param defaults: Default attributes for epochs, including cloning_rate
            and selfing_rate.
        :return: Newly created deme.
        :rtype: :class:`.Deme`
        """
        # some basic deme property checks
        if id in self:
            raise ValueError(f"deme {id} already exists in this graph")
        if epochs is None:
            raise ValueError(f"deme {id} must have at least one specified epoch")
        if initial_size is None and epochs is not None:
            initial_size = epochs[0].initial_size
        if initial_size is None:
            raise ValueError(f"must set initial_size for deme {id}")
        if ancestors is None:
            ancestors = []
        if not isinstance(ancestors, list):
            raise TypeError(f"ancestors must be a list of deme IDs for deme {id}")
        for ancestor in ancestors:
            if ancestor not in self:
                raise ValueError(f"ancestor deme {ancestor} not in graph for deme {id}")
        if proportions is None:
            if len(ancestors) == 1:
                proportions = [1.0]
            else:
                proportions = []

        # set the start time to first epoch's start time.
        # if first epoch does not have a start time, set to inf or to
        # the ancestor's end time
        if start_time is None:
            if epochs[0].start_time is not None:
                start_time = epochs[0].start_time
            elif len(ancestors) > 0:
                if len(ancestors) > 1:
                    raise ValueError(
                        "with multiple ancestors, start_time must be specified "
                        f"for deme {id}"
                    )
                start_time = self[ancestors[0]].end_time
            else:
                start_time = float("inf")
        # the first epoch's start time is set to deme's start time
        if epochs[0].start_time is None:
            epochs[0].start_time = start_time
        elif epochs[0].start_time != start_time:
            raise ValueError(
                f"deme and first epoch start times do not align for deme {id}"
            )

        # set the end time to the last epoch's end time
        if end_time is None:
            end_time = epochs[-1].end_time
        if epochs[-1].end_time is not None and epochs[-1].end_time != end_time:
            raise ValueError(
                f"deme and final epoch end times do not align for deme {id}"
            )

        # check start time is valid wrt ancestor time intervals
        for ancestor in ancestors:
            anc = self[ancestor]
            if not (anc.start_time > start_time >= anc.end_time):
                raise ValueError(
                    f"start_time={start_time} is outside the interval "
                    f"of existence for ancestor {ancestor} "
                    f"({anc.start_time}, {anc.end_time})"
                )

        # set default cloning and selfing rates
        cloning_rate = defaults.get("cloning_rate", self.defaults.get("cloning_rate"))
        selfing_rate = defaults.get("selfing_rate", self.defaults.get("cloning_rate"))

        # fill in all attributes of epochs
        for i in range(len(epochs)):
            # set the start time based on the last epoch's end time
            if epochs[i].start_time is None:
                epochs[i].start_time = epochs[i - 1].end_time
            if epochs[i].end_time is None:
                raise ValueError("all epochs must specify the end time")
            if i > 0 and epochs[i].start_time != epochs[i - 1].end_time:
                raise ValueError(
                    "epoch start and end times do not align for deme {id}, "
                    f"epochs {i - 1} and {i}"
                )
            # for each subsequent epoch, fill in start size, final size,
            # and size function as necessary based on last epoch
            if epochs[i].initial_size is None:
                epochs[i].initial_size = epochs[i - 1].final_size
            if epochs[i].final_size is None:
                epochs[i].final_size = epochs[i].initial_size
            if epochs[i].size_function is None:
                if epochs[i].initial_size == epochs[i].final_size:
                    epochs[i].size_function = "constant"
                else:
                    epochs[i].size_function = "exponential"
            # set per-epoch selfing and cloning rates
            if epochs[i].selfing_rate is None:
                epochs[i].selfing_rate = selfing_rate
            if epochs[i].cloning_rate is None:
                epochs[i].cloning_rate = cloning_rate

        deme = Deme(
            id=id,
            description=description,
            ancestors=ancestors,
            proportions=proportions,
            epochs=epochs,
            defaults=defaults,
        )
        self._deme_map[deme.id] = deme
        self.demes.append(deme)
        return deme

    def _check_time_intersection(self, deme1, deme2, time):
        deme1 = self[deme1]
        deme2 = self[deme2]
        time_lo = max(deme1.end_time, deme2.end_time)
        time_hi = min(deme1.start_time, deme2.start_time)
        if time is not None:
            if not (time_lo <= time <= time_hi):
                raise ValueError(
                    f"{time} not in interval [{time_lo}, {time_hi}], "
                    f"as defined by the time-intersection of {deme1.id} "
                    f"(start_time={deme1.start_time}, end_time={deme1.end_time}) "
                    f"and {deme2.id} (start_time={deme2.start_time}, "
                    f"end_time={deme2.end_time})."
                )
        return time_lo, time_hi

    def symmetric_migration(
        self, *, demes, rate, start_time=None, end_time=None
    ) -> List[Migration]:
        """
        Add continuous symmetric migrations between all pairs of demes in a list.

        :param demes: list of deme IDs. Migration is symmetric between all
            pairs of demes in this list.
        :param rate: The rate of migration per generation.
        :param start_time: The time at which the migration rate is enabled.
        :param end_time: The time at which the migration rate is disabled.
        :return: List of newly created migrations.
        :rtype: list of :class:`.Migration`
        """
        if not isinstance(demes, list) or len(demes) < 2:
            raise ValueError("must specify a list of two or more deme IDs")
        migrations = list()
        for source, dest in itertools.permutations(demes, 2):
            migrations.append(
                self.migration(
                    source=source,
                    dest=dest,
                    rate=rate,
                    start_time=start_time,
                    end_time=end_time,
                )
            )
        return migrations

    def migration(
        self, *, source, dest, rate, start_time=None, end_time=None
    ) -> Migration:
        """
        Add continuous migration from one deme to another.
        Source and destination demes follow the forwards-in-time convention,
        so that the migration rate refers to the movement of individuals from
        the ``source`` deme to the ``dest`` deme.

        :param source: The ID of the source deme.
        :param dest: The ID of the destination deme.
        :param rate: The rate of migration per generation.
        :param start_time: The time at which the migration rate is enabled.
            If ``None``, the start time is defined by the earliest time at
            which the demes coexist.
        :param end_time: The time at which the migration rate is disabled.
            If ``None``, the end time is defined by the latest time at which
            the demes coexist.
        :return: Newly created migration.
        :rtype: :class:`.Migration`
        """
        for deme_id in (source, dest):
            if deme_id not in self:
                raise ValueError(f"{deme_id} not in graph")
        time_lo, time_hi = self._check_time_intersection(source, dest, start_time)
        if start_time is None:
            start_time = time_hi
        else:
            self._check_time_intersection(source, dest, start_time)
        if end_time is None:
            end_time = time_lo
        else:
            self._check_time_intersection(source, dest, end_time)
        for existing_migration in self.migrations:
            if source == existing_migration.source and dest == existing_migration.dest:
                if (
                    start_time >= existing_migration.start_time > end_time
                    or start_time > existing_migration.end_time >= end_time
                    or existing_migration.start_time
                    >= start_time
                    > existing_migration.end_time
                    or existing_migration.start_time
                    > end_time
                    >= existing_migration.end_time
                ):
                    raise ValueError(
                        "new migration overlaps exisiting migration "
                        f"from {source} to {dest}"
                    )
        migration = Migration(
            source=source,
            dest=dest,
            start_time=start_time,
            end_time=end_time,
            rate=rate,
        )

        self.migrations.append(migration)
        return migration

    def pulse(self, *, source, dest, proportion, time) -> Pulse:
        """
        Add a pulse of migration at a fixed time.
        Source and destination demes follow the forwards-in-time convention.

        :param source: The ID of the source deme.
        :param dest: The ID of the destination deme.
        :param proportion: At the instant after migration, this is the expected
            proportion of individuals in the destination deme made up of individuals
            from the source deme.
        :param time: The time at which migrations occur.
        :return: Newly created pulse.
        :rtype: :class:`.Pulse`
        """
        for deme_id in (source, dest):
            if deme_id not in self:
                raise ValueError(f"{deme_id} not in graph")
        self._check_time_intersection(source, dest, time)

        # Check for models that have multiple pulses defined at the same time.
        # E.g. chains of pulses like: deme0 -> deme1; deme1 -> deme2,
        # where reversing the order of the pulse definitions changes the
        # interpretation of the model. Such models are valid, but the behaviour
        # may not be what the user expects.
        # See https://github.com/popsim-consortium/demes-python/issues/46
        sources = set()
        dests = set()
        for pulse in self.pulses:
            if pulse.time == time:
                sources.add(pulse.source)
                dests.add(pulse.dest)
        if source in dests or dest in (sources | dests):
            warnings.warn(
                "Multiple pulses are defined for the same deme(s) at time "
                f"{time}. The ancestry proportions after this time will thus "
                "depend on the order in which the pulses have been specified. "
                "To avoid unexpected behaviour, the graph can instead "
                "be structured to introduce a new deme at this time with "
                "the desired ancestry proportions."
            )

        pulse = Pulse(
            source=source,
            dest=dest,
            time=time,
            proportion=proportion,
        )
        self.pulses.append(pulse)
        return pulse

    @property
    def successors(self):
        """
        Lists of successors for all demes in the graph.
        """
        succ = {}
        for deme_info in self.demes:
            succ.setdefault(deme_info.id, [])
            if deme_info.ancestors is not None:
                for a in deme_info.ancestors:
                    succ.setdefault(a, [])
                    succ[a].append(deme_info.id)
        return succ

    @property
    def predecessors(self):
        """
        Lists of predecessors (ancestors) for all demes in the graph.
        """
        pred = {}
        for deme_info in self.demes:
            pred.setdefault(deme_info.id, [])
            if deme_info.ancestors is not None:
                for a in deme_info.ancestors:
                    pred[deme_info.id].append(a)
        return pred

    def list_demographic_events(self):
        """
        Loop through successors/predecessors to generate a list of splits, branches,
        mergers, and admixtures. If a deme has more than one predecessor,
        then it is a merger or an admixture event, which we differentiate by end and
        start times of those demes. If a deme has a single predecessor, we check
        whether it is a branch (start time != predecessor's end time), or split.

        Returns a dictionary containing all discrete demographic events, including
        pulses that are listed as a Graph attribute.
        """
        demo_events = {
            "pulses": self.pulses,
            "splits": [],
            "branches": [],
            "mergers": [],
            "admixtures": [],
        }
        splits_to_add = {}
        for c, p in self.predecessors.items():
            if len(p) == 0:
                continue
            elif len(p) == 1:
                if self[c].start_time == self[p[0]].end_time:
                    splits_to_add.setdefault(p[0], set())
                    splits_to_add[p[0]].add(c)
                else:
                    demo_events["branches"].append(
                        Branch(parent=p[0], child=c, time=self[c].start_time)
                    )
            else:
                time_aligned = True
                for deme_from in p:
                    if self[c].start_time != self[deme_from].end_time:
                        time_aligned = False
                if time_aligned is True:
                    demo_events["mergers"].append(
                        Merge(
                            parents=self[c].ancestors,
                            proportions=self[c].proportions,
                            child=c,
                            time=self[c].start_time,
                        )
                    )
                else:
                    demo_events["admixtures"].append(
                        Admix(
                            parents=self[c].ancestors,
                            proportions=self[c].proportions,
                            child=c,
                            time=self[c].start_time,
                        )
                    )
        for deme_from, demes_to in splits_to_add.items():
            demo_events["splits"].append(
                Split(
                    parent=deme_from,
                    children=list(demes_to),
                    time=self[deme_from].end_time,
                )
            )
        return demo_events

    def validate(self):
        """
        Validates the demographic model.
        """
        self.fromdict(self.asdict())

    def in_generations(self):
        """
        Return a copy of the graph with times in units of generations.
        """
        graph = copy.deepcopy(self)
        graph.time_units = "generations"
        generation_time = self.generation_time
        if generation_time is not None:
            graph.generation_time = None
            for deme in graph.demes:
                for epoch in deme.epochs:
                    epoch.start_time /= generation_time
                    epoch.end_time /= generation_time
            for migration in graph.migrations:
                migration.start_time /= generation_time
                migration.end_time /= generation_time
            for pulse in graph.pulses:
                pulse.time /= generation_time
        return graph

    @classmethod
    def fromdict(cls, data):
        """
        Return a graph from a dict representation. The inverse of asdict().
        """
        g = cls(
            description=data.get("description"),
            time_units=data.get("time_units"),
            generation_time=data.get("generation_time"),
            doi=data.get("doi", []),
            defaults=data.get("defaults", {}),
        )

        for deme in data.get("demes", []):
            if "epochs" in deme:
                deme["epochs"] = [Epoch(**epoch) for epoch in deme["epochs"]]
            g.deme(**deme)
        for migration_type, migration_list in data.get("migrations", dict()).items():
            if migration_type == "symmetric":
                for m in migration_list:
                    g.symmetric_migration(**m)
            if migration_type == "asymmetric":
                for m in migration_list:
                    g.migration(**m)
        for pulse in data.get("pulses", []):
            g.pulse(**pulse)
        return g

    def asdict(self):
        """
        Return a dict representation of the graph.
        """

        def filt(_attrib, val):
            return val is not None and not (hasattr(val, "__len__") and len(val) == 0)

        def coerce_numbers(inst, attribute, value):
            # Explicitly convert numeric types to int or float, so that they
            # don't cause problems for the YAML and JSON serialisers.
            # E.g. numpy int32/int64 are part of Python's numeric tower as
            # subclasses of numbers.Integral, similarly numpy's float32/float64
            # are subclasses of numbers.Real. There are yet other numeric types,
            # such as the standard library's decimal.Decimal, which are not part
            # of the numeric tower, but provide a __float__() method.
            if isinstance(value, numbers.Integral):
                value = int(value)
            elif isinstance(value, numbers.Real) or hasattr(value, "__float__"):
                value = float(value)
            return value

        data = attr.asdict(self, filter=filt, value_serializer=coerce_numbers)
        # translate to spec data model
        for deme in data["demes"]:
            deme["start_time"] = deme["epochs"][0]["start_time"]
            deme["end_time"] = deme["epochs"][-1]["end_time"]
        migrations = data.pop("migrations", None)
        if migrations is not None:
            data["migrations"] = {"asymmetric": migrations}
        return data

    def asdict_simplified(self, custom_attributes=[]):
        """
        Return a simplified dict representation of the graph.

        :param custom_attributes: List of additional attributes to simplify, which
            are not ``selfing_rate`` or ``cloning_rate``.
        """
        if not isinstance(custom_attributes, list):
            raise TypeError("custom_attributes must be a list of attributes")

        def simplify_epochs(data):
            """
            Remove epoch start times if implied by previous epoch's end time
            or if implied by the deme ancestor(s)'s end time(s).
            """
            for deme in data["demes"]:
                for j, epoch in enumerate(deme["epochs"]):
                    # remove implied start times
                    if j == 0:
                        if math.isinf(epoch["start_time"]):
                            del epoch["start_time"]
                        if "ancestors" in deme and len(deme["ancestors"]) == 1:
                            # start time needed for more than 1 ancestor
                            if (
                                self[deme["ancestors"][0]].end_time
                                == epoch["start_time"]
                            ):
                                del epoch["start_time"]
                    else:
                        del epoch["start_time"]
                    if epoch["size_function"] in ("constant", "exponential"):
                        del epoch["size_function"]
                    if epoch["initial_size"] == epoch["final_size"]:
                        del epoch["final_size"]

            for deme in data["demes"]:
                del deme["start_time"]
                del deme["end_time"]
                if "ancestors" in deme and len(deme["ancestors"]) == 1:
                    del deme["proportions"]

        def simplify_migration_rates(data):
            """
            Collapse symmetric migration rates, and remove redundant information
            about start and end times if they are implied by the time overlap
            interval of the demes involved.

            To collapse symmetric migrations, we collect all source/dest migration
            pairs for each set of migration attributes (rate, start_time, end_time),
            and then iteratively check for all-way symmetric migration between all
            demes that are involved in migrations for the given set of migration
            attributes.
            """

            def collapse_demes(pairs):
                all_demes = []
                for pair in pairs:
                    if pair[0] not in all_demes:
                        all_demes.append(pair[0])
                    if pair[1] not in all_demes:
                        all_demes.append(pair[1])
                return all_demes

            symmetric = []
            asymmetric = data["migrations"]["asymmetric"].copy()
            # first remove start/end times if equal time intersections
            rate_sets = {}
            # keys of rate_types are (rate, start_time, end_time)
            for migration in data["migrations"]["asymmetric"]:
                source = migration["source"]
                dest = migration["dest"]
                time_lo, time_hi = self._check_time_intersection(source, dest, None)
                if migration["end_time"] == time_lo:
                    del migration["end_time"]
                if migration["start_time"] == time_hi:
                    del migration["start_time"]
                k = tuple(
                    migration.get(key) for key in ("rate", "start_time", "end_time")
                )
                rate_sets.setdefault(k, [])
                rate_sets[k].append((source, dest))

            for k, pairs in rate_sets.items():
                if len(pairs) == 1:
                    continue
                # list of all demes that are source or dest in this rate set
                all_demes = collapse_demes(pairs)

                # we check all possible sets of n-way symmetric migration
                i = len(all_demes)
                while len(all_demes) >= 2 and i >= 2:
                    # loop through each possible set for a given set size i
                    compress_demes = False
                    for deme_set in itertools.combinations(all_demes, i):
                        # check if all (source, dest) pairs exist in pairs of migration
                        all_present = True
                        for deme_pair in itertools.permutations(deme_set, 2):
                            if deme_pair not in pairs:
                                all_present = False
                                break
                        # if they do all exist
                        if all_present:
                            compress_demes = True
                            # remove from asymmetric list
                            for deme_pair in itertools.permutations(deme_set, 2):
                                mig = {
                                    "source": deme_pair[0],
                                    "dest": deme_pair[1],
                                    "rate": k[0],
                                }
                                if k[1] is not None:
                                    mig["start_time"] = k[1]
                                if k[2] is not None:
                                    mig["end_time"] = k[2]
                                asymmetric.remove(mig)
                                pairs.remove(deme_pair)
                            # add to symmetric list
                            sym_mig = dict(demes=[d for d in deme_set], rate=k[0])
                            if k[1] is not None:
                                sym_mig["start_time"] = k[1]
                            if k[2] is not None:
                                sym_mig["end_time"] = k[2]
                            symmetric.append(sym_mig)
                    # if we found a set of symmetric migrations, compress all_demes
                    if compress_demes:
                        all_demes = collapse_demes(pairs)
                        i = min(i, len(all_demes))
                    # otherwise, check one set size smaller
                    else:
                        i -= 1

            if len(symmetric) > 0:
                data["migrations"]["symmetric"] = symmetric
            if len(asymmetric) == 0:
                del data["migrations"]["asymmetric"]
            else:
                data["migrations"]["asymmetric"] = asymmetric

        data = self.asdict()

        if "migrations" in data:
            simplify_migration_rates(data)
        simplify_epochs(data)

        return data
