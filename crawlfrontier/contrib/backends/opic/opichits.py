"""
An implementation of the OPIC-HITS algorithm
"""
import hitsdb
import graphdb
import relevancedb


class OpicHits(object):
    """Implements the OPIC algorithm applied to the HITS scores problem"""

    def __init__(
            self,
            db_graph=None,
            db_scores=None,
            time_window=None,
            db_relevance=None
    ):
        """
        :param db_graph: Read only graph database. If None create a new one
                         using :class:`SQLite <.graphdb.SQLite>`
        :param db_scores: Scores database. If None create a new one using
                         :class:`SQLite <.hitsdb.SQLite>`
        :param time_window: Ignore cash flow out of this time window.
                            Set to False/None to ignore.
        :param db_relevance: Read only relevance database. If None create a
                             new one using :class:`SQLite <.relevancedb.SQLite>`

        :type db_graph: :class:`GraphInterface <.graphdb.GraphInterface>`
        :type db_scores: :class:`HitsDBInterface <.hitsdb.HitsDBInterface>`
        :type time_window: float
        :type db_relevance: :class:`RelevanceDBInterface <.relevancedb.RelevanceDBInterface>`
        """
        # Web page connectivity information
        self._graph = db_graph or graphdb.SQLite()

        # HITS score associated to each web page
        self._scores = db_scores or hitsdb.SQLite()

        # Number of scored web pages
        self._n_pages = self._scores.get_count()

        # Total hub history
        self._h_total = self._scores.get_h_total()

        # Total authority history
        self._a_total = self._scores.get_a_total()

        # Relevance database
        self._relevance = db_relevance or relevancedb.SQLite()

        # A list of pages to update
        self._to_update = []

        self._closed = False

        self._time_window = time_window
        self._time = 0.0

        # A virtual page connected from and to every
        # other web page
        self._virtual_page = hitsdb.HitsScore(
            h_history=0.0,
            h_cash=1.0,
            h_last=0.0,
            a_history=0.0,
            a_cash=1.0,
            a_last=0.0
        )

        # Initialize scores
        for page_id in self._graph.inodes():
            self.add_page(page_id)

    def mark_update(self, page_id):
        """Add this to the list of pages to update

        To decide which pages we should update next we uuse an heuristic:
        we select the pages with the highest accumulated authority or hub cash.
        This function makes possible to externally add a given page to the set
        of pages to be updated, irrespective of its accumulated cash.

        :param str page_id: Page identification
        """
        self._to_update.append(page_id)

    def add_page(self, page_id):
        """Add a new page

        :param str page_id: Page identification
        :returns: :class:`HitsScore <.hitsdb.HitsScore>` --
                  The new score assigned to the page
        """
        if page_id not in self._scores:
            self._n_pages += 1

            new_score = hitsdb.HitsScore(
                h_history=0.0,
                h_cash=1.0,
                h_last=self._time,
                a_history=0.0,
                a_cash=1.0,
                a_last=self._time
            )

            self._scores.add(page_id, new_score)
        else:
            new_score = None

        return new_score

    def _get_page_score(self, page_id):
        """Return HITS score information.

        If page has not been  associated yet it will create a new association
        """

        score = self.add_page(page_id)
        if not score:
            score = self._scores.get(page_id)

        return score

    def _history_interpolator(self, delta, history, cash):
        """Estimates cash added inside self._time_window"""
        f = delta/self._time_window
        if f < 1.0:
            new_history = history*(1.0 - f) + cash
        else:
            new_history = cash/f

        return new_history

    def _updated_page_h(self, page_score):
        """Return a new HitsScore instance, where cash has been moved to
        history
        """

        if not self._time_window:
            h_history_new = page_score.h_history + page_score.h_cash
        else:
            h_history_new = self._history_interpolator(
                self._time - page_score.h_last,
                page_score.h_history,
                page_score.h_cash)

        return hitsdb.HitsScore(
            h_history=h_history_new,
            h_cash=0,
            h_last=self._time,
            a_history=page_score.a_history,
            a_cash=page_score.a_cash,
            a_last=page_score.a_last
        )

    def _updated_page_a(self, page_score):
        """Return a new HitsScore instance, where cash has been moved to
        history
        """

        if not self._time_window:
            a_history_new = page_score.a_history + page_score.a_cash
        else:
            a_history_new = self._history_interpolator(
                self._time - page_score.a_last,
                page_score.a_history,
                page_score.a_cash)

        return hitsdb.HitsScore(
            h_history=page_score.h_history,
            h_cash=page_score.h_cash,
            h_last=page_score.h_last,
            a_history=a_history_new,
            a_cash=0,
            a_last=self._time
        )

    def _update_virtual_page(self):
        """Repeat update_page, but on the virtual page"""

        if self._n_pages > 0:
            h_dist = self._virtual_page.a_cash/self._n_pages
            a_dist = self._virtual_page.h_cash/self._n_pages

            self._scores.increase_all_cash(h_dist, a_dist)

            self._virtual_page = self._updated_page_h(
                self._updated_page_a(
                    self._virtual_page))

    def _update_page_h(self, page_id):
        """Update HITS score for the given page"""

        score = self._get_page_score(page_id)

        succ = self._graph.successors(page_id)

        a_dist = score.h_cash/float(len(succ) + 1.0)
        self._scores.increase_a_cash(succ, a_dist)
        self._virtual_page.a_cash += a_dist

        # Update own-score info
        new_score = self._updated_page_h(score)
        self._scores.set(page_id, new_score)

        # Add cash to total cash count
        self._h_total += new_score.h_history - score.h_history
        self._time += score.h_cash

    def _update_page_a(self, page_id):
        """Update HITS score for the given page"""

        score = self._get_page_score(page_id)

        # Authority cash gets distributed to hubs
        pred = self._graph.predecessors(page_id)
        N = len(pred)

        # Relevance is scored between 0 and 1. 0.5 means we have no
        # information on it.
        r = self._relevance.get(page_id) or 0.5

        # Distribute to each hub: a_cash*z(r)
        # Distribute to VP      : a_cash*(1.0 - N*z(r))
        #
        # z(0  ) = 0             If r = 0.0 no cash goes back to hubs
        # z(1  ) = 1/N           If r = 1.0 all cash go back to hubs
        # z(0.5) = 1 - N*z(0.5)  If r = 0.5 then the virtual page counts as any
        #                                   other page
        # Compute z(r) as a second order polynomial fitting the above points.
        # If N == 0 then z is undefined, and actually any value is valid
        z = 2.0*r/N*(2.0*N/(N + 1)*(1 - r) + (r - 0.5)) if N > 0 else 0.0

        self._scores.increase_h_cash(pred, score.a_cash*z)
        self._virtual_page.h_cash += score.a_cash*(1.0 - z*N)

        # Update own-score info
        new_score = self._updated_page_a(score)
        self._scores.set(page_id, new_score)

        # Add cash to total cash count
        self._a_total += new_score.a_history - score.a_history
        self._time += score.a_cash

    def update(self, n_iter=1):
        """Run a full iteration of the OPIC-HITS algorithm

        :param int n_iter: number of iterations
        :returns: pair of lists -- The first one contains pages with an updated
                  hub score and the second ones with update authority score.
        """

        # update proportional to the rate of graph grow
        n_updates = 20*max(1, len(self._to_update))
        for i in xrange(n_iter):
            highest_h = self._scores.get_highest_h_cash(n_updates)
            highest_a = self._scores.get_highest_a_cash(n_updates)

            mixed = sorted(
                [(cash, page_id, True) for page_id, cash in highest_h] +
                [(cash, page_id, False) for page_id, cash in highest_a],
                reverse=True
            )[:n_updates]

            for cash, page_id, is_hub in mixed:
                if is_hub:
                    self._update_page_h(page_id)
                else:
                    self._update_page_a(page_id)

            self._update_virtual_page()

        self._to_update = []

        return ([page_id for cash, page_id, hub in mixed if hub],
                [page_id for cash, page_id, hub in mixed if not hub])

    def _relative_score(self, score):
        return (
            score.h_history/self._h_total if self._h_total > 0 else 0.0,
            score.a_history/self._a_total if self._a_total > 0 else 0.0
        )

    def get_scores(self, page_id):
        """Normalized hub and authority score

        :param str page_id: Page identification
        :returns: (float, float) -- A tuple (hub score, authority score) for
                  the given page_id
        """

        return self._relative_score(self._get_page_score(page_id))

    def iscores(self):
        """Iterate over (page id, hub score, authority score)"""
        for page_id, score in self._scores.iteritems():
            yield (page_id,) + self._relative_score(score)

    def close(self):
        """Close any associated database"""
        if not self._closed:
            self._scores.close()

        self._closed = True

    @property
    def h_mean(self):
        """Mean of hub scores"""
        return self._h_total/self._n_pages if self._n_pages > 0 else 1.0

    @property
    def a_mean(self):
        """Mean of authority scores"""
        return self._a_total/self._n_pages if self._n_pages > 0 else 1.0
