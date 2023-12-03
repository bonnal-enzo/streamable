import itertools
from abc import ABC, abstractmethod
from typing import (
    Any,
    Iterator,
    List,
    TypeVar,
)

from kioss import _exec, _concurrent_exec, _util, _plan

T = TypeVar("T")

class AVisitor(ABC):
    @abstractmethod
    def visitSourcePipe(self, pipe: _plan.SourcePipe) -> Any:
        raise NotImplementedError()

    @abstractmethod
    def visitMapPipe(self, pipe: _plan.MapPipe) -> Any:
        raise NotImplementedError()

    @abstractmethod
    def visitFlattenPipe(self, pipe: _plan.FlattenPipe) -> Any:
        raise NotImplementedError()

    @abstractmethod
    def visitChainPipe(self, pipe: _plan.ChainPipe) -> Any:
        raise NotImplementedError()

    @abstractmethod
    def visitFilterPipe(self, pipe: _plan.FilterPipe) -> Any:
        raise NotImplementedError()

    @abstractmethod
    def visitBatchPipe(self, pipe: _plan.BatchPipe) -> Any:
        raise NotImplementedError()

    @abstractmethod
    def visitSlowPipe(self, pipe: _plan.SlowPipe) -> Any:
        raise NotImplementedError()

    @abstractmethod
    def visitCatchPipe(self, pipe: _plan.CatchPipe) -> Any:
        raise NotImplementedError()

    @abstractmethod
    def visitLogPipe(self, pipe: _plan.LogPipe) -> Any:
        raise NotImplementedError()

class IteratorGeneratingVisitor(AVisitor):

    def visitSourcePipe(self, pipe: _plan.SourcePipe[T]) -> Iterator[T]:
        iterator = pipe.source()
        try:
            # duck-type checks that the object returned by the source is an iterator
            _util.duck_check_type_is_iterator(iterator)
        except TypeError as e:
            raise TypeError(
                f"source must be a callable returning an iterator (implements __iter__ and __next__ methods), but the object resulting from a call to source() was not an iterator: got '{iterator}' of type {type(iterator)}."
            ) from e
        return iterator

    def visitMapPipe(self, pipe: _plan.MapPipe[T]) -> Iterator[T]:
        if pipe.n_threads == 1:
            return map(pipe.func, pipe.upstream._accept(self))
        else:
            return _concurrent_exec.ThreadedMappingIteratorWrapper(
                pipe.upstream._accept(self), pipe.func, n_workers=pipe.n_threads
            ) 

    def visitFlattenPipe(self, pipe: _plan.FlattenPipe[T]) -> Iterator[T]:
        if pipe.n_threads == 1:
            return _exec.FlatteningIteratorWrapper(pipe.upstream._accept(self))
        else:
            return _concurrent_exec.ThreadedFlatteningIteratorWrapper(
                pipe.upstream._accept(self), n_workers=pipe.n_threads
            )

    def visitChainPipe(self, pipe: _plan.ChainPipe[T]) -> Iterator[T]:
        return itertools.chain(pipe.upstream._accept(self), *list(map(iter, pipe.others)))

    def visitFilterPipe(self, pipe: _plan.FilterPipe[T]) -> Iterator[T]:
        return filter(pipe.predicate, pipe.upstream._accept(self))

    def visitBatchPipe(self, pipe: _plan.BatchPipe[T]) -> Iterator[List[T]]:
        return _exec.BatchingIteratorWrapper(
            iter(pipe.upstream), pipe.size, pipe.period
        )

    def visitSlowPipe(self, pipe: _plan.SlowPipe[T]) -> Iterator[T]:
        return _exec.SlowingIteratorWrapper(pipe.upstream._accept(self), pipe.freq)

    def visitCatchPipe(self, pipe: _plan.CatchPipe[T]) -> Iterator[T]:
        return _exec.CatchingIteratorWrapper(
            pipe.upstream._accept(self), *pipe.classes, when=pipe.when
        )

    def visitLogPipe(self, pipe: _plan.LogPipe[T]) -> Iterator[T]:
        return _exec.LoggingIteratorWrapper(pipe.upstream._accept(self), pipe.what)
