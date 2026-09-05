import abc
import dataclasses

from ingestion.models import Provider, SourceType


@dataclasses.dataclass(frozen=True)
class FetchTarget:
    """
    One fetchable unit — usually a URL. A fetcher can have several (e.g.
    Veolia's site is paginated across 3 URLs); each target becomes its
    own RawContent row so a failure on one page doesn't lose the others
    or abort the whole run.
    """

    reference: str


class BaseFetcher(abc.ABC):
    provider: Provider
    source_type: SourceType

    @abc.abstractmethod
    def fetch_targets(self) -> list[FetchTarget]:
        """List everything this fetcher should hit on a single run."""

    def fetch_one(self, target: FetchTarget) -> str:
        """
        Fetch a single target's raw content. Default assumes
        `target.reference` is a plain URL to GET; override if a
        provider ever needs something other than a simple HTTP GET.

        Must raise FetchError (or let one propagate from fetch_page_text)
        on failure — never return partial/garbage content silently.
        """
        from ingestion.fetchers.http import fetch_page_text

        return fetch_page_text(target.reference)
