from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Collection,
    Generic,
    Iterable,
    Iterator,
    List,
    Optional,
    Sequence,
    Set,
    Type,
    TypeVar,
    overload,
)

from streamable import _util

if TYPE_CHECKING:
    import builtins

    from streamable._visit._base import Visitor

R = TypeVar("R")
T = TypeVar("T")
V = TypeVar("V")


class Stream(Iterable[T]):
    _RUN_MAX_NUM_ERROR_SAMPLES = 8

    def __init__(self, source: Callable[[], Iterable[T]]) -> None:
        """
        Initialize a Stream by providing a source iterable.

        Args:
            source (Callable[[], Iterator[T]]): The data source. This function is used to provide a fresh iterable to each iteration over the stream.
        """
        self.upstream: "Optional[Stream]" = None
        if not callable(source):
            raise TypeError(f"source must be a callable but got a {type(source)}")
        self.source = source

    def __iter__(self) -> Iterator[T]:
        from streamable._visit import _iter

        return self._accept(_iter.IteratorProducingVisitor[T]())

    def __add__(self, other: "Stream[T]") -> "Stream[T]":
        """
        a + b is syntax sugar for a.chain(b).
        """
        return self.chain(other)

    def explain(self, colored: bool = False) -> str:
        """
        Returns a friendly representation of this stream operations.
        """
        from streamable._visit import _explanation

        return self._accept(_explanation.ExplainingVisitor(colored))

    def _accept(self, visitor: "Visitor[V]") -> V:
        return visitor.visit_source_stream(self)

    @staticmethod
    def _validate_concurrency(concurrency: int):
        if concurrency < 1:
            raise ValueError(
                f"`concurrency` should be greater or equal to 1, but got {concurrency}."
            )

    def map(
        self,
        func: Callable[[T], R],
        concurrency: int = 1,
    ) -> "Stream[R]":
        """
        Apply `func` to the upstream elements and yield the results in order.

        Args:
            func (Callable[[T], R]): The function to be applied to each element.
            concurrency (int): The number of threads used to concurrently apply the function (default is 1, meaning no concurrency).
        Returns:
            Stream[R]: A stream of results of `func` applied to upstream elements.
        """
        Stream._validate_concurrency(concurrency)
        return MapStream(self, func, concurrency)

    def do(
        self,
        func: Callable[[T], Any],
        concurrency: int = 1,
    ) -> "Stream[T]":
        """
        Call `func` on upstream elements, discarding the result and yielding upstream elements unchanged and in order.
        If `func(elem)` throws an exception, then this exception will be thrown when iterating over the stream and `elem` will not be yielded.

        Args:
            func (Callable[[T], Any]): The function to be applied to each element.
            concurrency (int): The number of threads used to concurrently apply the function (default is 1, meaning no concurrency).
        Returns:
            Stream[T]: A stream of upstream elements, unchanged.
        """
        Stream._validate_concurrency(concurrency)
        return DoStream(self, func, concurrency)

    @overload
    def flatten(
        self: "Stream[Iterable[R]]",
        concurrency: int = 1,
    ) -> "Stream[R]":
        ...

    @overload
    def flatten(
        self: "Stream[Collection[R]]",
        concurrency: int = 1,
    ) -> "Stream[R]":
        ...

    @overload
    def flatten(
        self: "Stream[Stream[R]]",
        concurrency: int = 1,
    ) -> "Stream[R]":
        ...

    @overload
    def flatten(
        self: "Stream[Iterator[R]]",
        concurrency: int = 1,
    ) -> "Stream[R]":
        ...

    @overload
    def flatten(
        self: "Stream[List[R]]",
        concurrency: int = 1,
    ) -> "Stream[R]":
        ...

    @overload
    def flatten(
        self: "Stream[Sequence[R]]",
        concurrency: int = 1,
    ) -> "Stream[R]":
        ...

    @overload
    def flatten(
        self: "Stream[builtins.map[R]]",
        concurrency: int = 1,
    ) -> "Stream[R]":
        ...

    @overload
    def flatten(
        self: "Stream[builtins.filter[R]]",
        concurrency: int = 1,
    ) -> "Stream[R]":
        ...

    @overload
    def flatten(
        self: "Stream[Set[R]]",
        concurrency: int = 1,
    ) -> "Stream[R]":
        ...

    def flatten(
        self: "Stream[Iterable[R]]",
        concurrency: int = 1,
    ) -> "Stream[R]":
        """
        Iterate over upstream elements, assumed to be iterables, and individually yield the sub-elements.

        Args:
            concurrency (int): The number of threads used to concurrently flatten the upstream iterables (default is 1, meaning no concurrency).
        Returns:
            Stream[R]: A stream of flattened elements from upstream iterables.
        """
        Stream._validate_concurrency(concurrency)
        return FlattenStream(self, concurrency)

    def chain(self, *others: "Stream[T]") -> "Stream[T]":
        """
        Yield the elements of the chained streams, in order.
        The elements of a given stream are yielded after its predecessor is exhausted.

        Args:
            *others (Stream[T]): One or more streams to chain with this stream.

        Returns:
            Stream[T]: A stream of elements of each stream in the chain, in order.
        """
        return ChainStream(self, list(others))

    def filter(self, predicate: Callable[[T], bool]) -> "Stream[T]":
        """
        Filter the elements of the stream based on the given predicate.

        Args:
            predicate (Callable[[T], bool]): The function that decides whether an element should be kept or not.

        Returns:
            Stream[T]: A stream of upstream elements satisfying the predicate.
        """
        return FilterStream(self, predicate)

    def batch(self, size: int, seconds: float = float("inf")) -> "Stream[List[T]]":
        """
        Yield upstream elements grouped in lists.
        A list will have ` size` elements unless:
        - an exception occurs upstream, the batch prior to the exception is yielded uncomplete.
        - the time elapsed since the last yield of a batch is greater than `seconds`.
        - upstream is exhausted.

        Args:
            size (int): Maximum number of elements per batch.
            seconds (float, optional): Maximum number of seconds between two yields (default is infinity).

        Returns:
            Stream[List[T]]: A stream of upstream elements batched into lists.
        """
        if size < 1:
            raise ValueError(f"batch's size should be >= 1 but got {size}.")
        if seconds <= 0:
            raise ValueError(f"batch's seconds should be > 0 but got {seconds}.")
        return BatchStream(self, size, seconds)

    def slow(self, frequency: float) -> "Stream[T]":
        """
        Slow down the iteration down to a maximum `frequency` = maximum number of elements yielded per second.

        Args:
            frequency (float): The maximum number of elements yielded per second.

        Returns:
            Stream[T]: A stream yielding upstream elements at a maximum `frequency`.
        """
        if frequency <= 0:
            raise ValueError(
                f"frequency is the maximum number of elements to yield per second, it must be > 0  but got {frequency}."
            )
        return SlowStream(self, frequency)

    def catch(
        self,
        *classes: Type[Exception],
        when: Optional[Callable[[Exception], bool]] = None,
    ) -> "Stream[T]":
        """
        Catches the upstream exceptions whose type is in `classes` and satisfying the `when` predicate if provided.

        Args:
            classes (Type[Exception]): The classes of exception to be catched.
            when (Callable[[Exception], bool], optional): An additional condition that must be satisfied to catch the exception.

        Returns:
            Stream[T]: A stream of upstream elements catching the eligible exceptions.
        """
        return CatchStream(self, *classes, when=when)

    def observe(self, what: str = "elements", colored: bool = False) -> "Stream[T]":
        """
        Logs the evolution of the iteration over elements.

        A logarithmic scale is used to prevent logs flood:
        - a 1st log is produced for the yield of the 1st element
        - a 2nd log is produced when we reach the 2nd element
        - a 3rd log is produced when we reach the 4th element
        - a 4th log is produced when we reach the 8th element
        - ...

        Args:
            what (str): (plural) name representing the objects yielded.
            colored (bool): whether or not to use ascii colorization.

        Returns:
            Stream[T]: A stream of upstream elements whose iteration is logged for observability.
        """
        return ObserveStream(self, what, colored)

    def iterate(
        self,
        collect_limit: int = 0,
        raise_if_more_errors_than: int = 0,
        fail_fast: bool = False,
    ) -> List[T]:
        """
        Run the Stream:
        - iterates over it until it is exhausted,
        - logs
        - catches exceptions log a sample of them at the end of the iteration
        - raises the first encountered error if more exception than `raise_if_more_errors_than` are catched during iteration.
        - else returns a sample of the output elements

        Args:
            raise_if_more_errors_than (int, optional): An error will be raised if the number of encountered errors is more than this threshold (default is 0).
            collect_limit (int, optional): How many output elements to return (default is 0).
            fail_fast (bool, optional): Decide to raise at the first encountered exception or at the end of the iteration (default is False).
        Returns:
            List[T]: A list containing the elements of the Stream titeratecate to the first `n_samples` ones.
        Raises:
            Exception: If more exception than `raise_if_more_errors_than` are catched during iteration.
        """
        if collect_limit < 0:
            raise ValueError(f"`collect_limit` must be >= 0  but got {collect_limit}.")
        if raise_if_more_errors_than < 0:
            raise ValueError(
                f"`raise_if_more_errors_than` must be >= 0  but got {raise_if_more_errors_than}."
            )

        max_num_error_samples = self._RUN_MAX_NUM_ERROR_SAMPLES
        stream = self

        if not isinstance(self, ObserveStream):
            stream = self.observe("output elements")

        error_samples: List[Exception] = []
        errors_count = 0

        if not fail_fast:

            def register_error_sample(error):
                nonlocal errors_count
                errors_count += 1
                if len(error_samples) < max_num_error_samples:
                    error_samples.append(error)
                return True

            stream = stream.catch(Exception, when=register_error_sample)

        _util.LOGGER.info(stream.explain(colored=False))

        output_samples: List[T] = []
        for elem in stream:
            if len(output_samples) < collect_limit:
                output_samples.append(elem)

        if errors_count > 0:
            _util.LOGGER.error(
                "first %s error samples: %s\nWill now raise the first of them:",
                max_num_error_samples,
                list(map(repr, error_samples)),
            )
            if raise_if_more_errors_than < errors_count:
                raise error_samples[0]

        return output_samples


X = TypeVar("X")
Y = TypeVar("Y")
Z = TypeVar("Z")


class FilterStream(Stream[Y]):
    def __init__(self, upstream: Stream[Y], predicate: Callable[[Y], bool]):
        self.upstream: Stream[Y] = upstream
        self.predicate = predicate

    def _accept(self, visitor: "Visitor[V]") -> V:
        return visitor.visit_filter_stream(self)


class MapStream(Stream[Z], Generic[Y, Z]):
    def __init__(self, upstream: Stream[Y], func: Callable[[Y], Z], concurrency: int):
        self.upstream: Stream[Y] = upstream
        self.func = func
        self.concurrency = concurrency

    def _accept(self, visitor: "Visitor[V]") -> V:
        return visitor.visit_map_stream(self)


class DoStream(Stream[Y]):
    def __init__(self, upstream: Stream[Y], func: Callable[[Y], Any], concurrency: int):
        self.upstream: Stream[Y] = upstream
        self.func = func
        self.concurrency = concurrency

    def _accept(self, visitor: "Visitor[V]") -> V:
        return visitor.visit_do_stream(self)


class ObserveStream(Stream[Y]):
    def __init__(self, upstream: Stream[Y], what: str, colored: bool):
        self.upstream: Stream[Y] = upstream
        self.what = what
        self.colored = colored

    def _accept(self, visitor: "Visitor[V]") -> V:
        return visitor.visit_observe_stream(self)


class FlattenStream(Stream[Y]):
    def __init__(self, upstream: Stream[Iterable[Y]], concurrency: int) -> None:
        self.upstream: Stream[Iterable[Y]] = upstream
        self.concurrency = concurrency

    def _accept(self, visitor: "Visitor[V]") -> V:
        return visitor.visit_flatten_stream(self)


class BatchStream(Stream[List[Y]]):
    def __init__(self, upstream: Stream[Y], size: int, seconds: float):
        self.upstream: Stream[Y] = upstream
        self.size = size
        self.seconds = seconds

    def _accept(self, visitor: "Visitor[V]") -> V:
        return visitor.visit_batch_stream(self)


class CatchStream(Stream[Y]):
    def __init__(
        self,
        upstream: Stream[Y],
        *classes: Type[Exception],
        when: Optional[Callable[[Exception], bool]] = None,
    ):
        self.upstream: Stream[Y] = upstream
        self.classes = classes
        self.when = when

    def _accept(self, visitor: "Visitor[V]") -> V:
        return visitor.visit_catch_stream(self)


class ChainStream(Stream[Y]):
    def __init__(self, upstream: Stream[Y], others: List[Stream]):
        self.upstream: Stream[Y] = upstream
        self.others = others

    def _accept(self, visitor: "Visitor[V]") -> V:
        return visitor.visit_chain_stream(self)


class SlowStream(Stream[Y]):
    def __init__(self, upstream: Stream[Y], frequency: float):
        self.upstream: Stream[Y] = upstream
        self.frequency = frequency

    def _accept(self, visitor: "Visitor[V]") -> V:
        return visitor.visit_slow_stream(self)
