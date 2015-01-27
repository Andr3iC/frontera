"""
Store for each page the refresh frequency, and additional data
to be used by the PageTimer to maintain this frequency
"""
from abc import ABCMeta, abstractmethod

import sqlite


class FreqDBInterface(object):
    """Interface definition for every FreqDB database"""
    __metaclass__ = ABCMeta

    @abstractmethod
    def clear(self):
        """Delete all contents"""
        pass

    @abstractmethod
    def close(self):
        """Close connection and commit changes """
        pass

    @abstractmethod
    def add(self, page_id, page_freq):
        """Associate page_freq with page_id, where:

        :param str page_id: an string which identifies the page
        :param float page_freq: refresh frequency of the page (Hz)
        """
        pass

    @abstractmethod
    def set(self, page_id, page_freq):
        """Change the frequency associated with page_id"""
        pass

    @abstractmethod
    def delete(self, page_id):
        """Delete association"""
        pass

    @abstractmethod
    def get_next_pages(self, n=1):
        """
        Return the next pages, to maintain the desired frequency
        """
        pass


class SQLite(sqlite.Connection, FreqDBInterface):
    """SQLite based implementation for FreqDBInterface"""

    def __init__(self, db=None):
        """Make a new connection to a frequency database or, if
        None provided make a new in-memory
        """
        super(SQLite, self).__init__(db)

        self._cursor.executescript(
            """
            CREATE TABLE IF NOT EXISTS page_frequency (
                page_id   TEXT UNIQUE,
                frequency REAL,
                score     REAL
            );

            CREATE INDEX IF NOT EXISTS
                score_index on page_frequency(score);
            """
        )

    def clear(self):
        self._cursor.executescript(
            """
            DELETE FROM page_frequency;
            """
        )

    def _get_min_score(self):
        _min_score = self._cursor.execute(
            """
            SELECT score FROM page_frequency ORDER BY score ASC LIMIT 1
            """
        ).fetchone()

        return _min_score[0] if _min_score else 0.0

    def add(self, page_id, page_frequency, fresh=True):
        # If page_frequency is zero, then we do not add it
        if page_frequency > 0:
            score = self._get_min_score()
            if fresh:
                score += 1.0/page_frequency

            self._cursor.execute(
                """
                INSERT OR IGNORE INTO page_frequency VALUES (?,?,?)
                """,
                (page_id,
                 page_frequency,
                 score)
            )

    def set(self, page_id, page_frequency):
        if page_frequency == 0:
            self.delete(page_id)
        else:
            if page_id in self:
                self._cursor.execute(
                    """
                    UPDATE OR IGNORE page_frequency
                    SET frequency=?, score=score - 1.0/frequency + 1.0/?
                    WHERE page_id=?
                    """,
                    (page_frequency,
                     page_frequency,
                     page_id)
                )
            else:
                self.add(page_id, page_frequency)

    def delete(self, page_id):
        self._cursor.execute(
            """
            DELETE FROM page_frequency WHERE page_id=?
            """,
            (page_id,)
        )

    def get_next_pages(self, n=1):
        pages = self._cursor.execute(
            """
            SELECT page_id FROM page_frequency ORDER BY score ASC LIMIT ?
            """,
            (n,)
        ).fetchall()

        self._cursor.execute(
            """
            UPDATE OR IGNORE page_frequency SET score=score + 1.0/frequency
            WHERE page_id IN ({0})
            """.format(
                ','.join(["'" + p[0] + "'" for p in pages]))
        )

        return [p[0] for p in pages]

    def __contains__(self, page_id):
        return self._cursor.execute(
            """
            SELECT page_id FROM page_frequency WHERE page_id=? LIMIT 1
            """,
            (page_id,)
        ).fetchone() is not None
