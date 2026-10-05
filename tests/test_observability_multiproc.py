import glob
import os
import tempfile
from unittest import mock

from django.test import SimpleTestCase
from prometheus_client import CollectorRegistry, multiprocess
from prometheus_client.mmap_dict import MmapedDict, mmap_key

from manuspectrum.observability import multiproc

PIDS = 300
BUCKETS = ("0.1", "1.0", "+Inf")


def write(directory, filename, rows):
    store = MmapedDict(os.path.join(directory, filename))
    for key, value, timestamp in rows:
        store.write_value(key, value, timestamp)
    store.close()


def counter_key(**labels):
    return mmap_key("hits", "hits_total", list(labels), list(labels.values()), "Hits.")


def histogram_rows(pid):
    rows = []
    for position, bucket in enumerate(BUCKETS):
        key = mmap_key(
            "lat", "lat_bucket", ["route", "le"], ["home", bucket], "Latency."
        )
        rows.append((key, float(pid % 3 + position), 0.0))
    rows.append((mmap_key("lat", "lat_sum", ["route"], ["home"], "Latency."), 0.5, 0.0))
    rows.append(
        (mmap_key("lat", "lat_count", ["route"], ["home"], "Latency."), 2.0, 0.0)
    )
    return rows


def collect(directory):
    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry, path=directory)
    return registry


class ArchiveDeadProcessTests(SimpleTestCase):
    def fill(self, directory, pids):
        for pid in pids:
            write(directory, f"counter_{pid}.db", [(counter_key(a="x"), 3.0, 0.0)])
            write(directory, f"histogram_{pid}.db", histogram_rows(pid))
            write(
                directory,
                f"gauge_livesum_{pid}.db",
                [(mmap_key("live", "live", [], [], "Live."), 1.0, 5.0)],
            )

    def test_three_hundred_dead_processes_leave_archives_and_live_pids_only(self):
        with tempfile.TemporaryDirectory() as directory:
            pids = list(range(1000, 1000 + PIDS))
            live = (4, 5)
            self.fill(directory, pids)
            self.fill(directory, live)
            before = collect(directory).get_sample_value("hits_total", {"a": "x"})
            sizes = []
            for pid in pids:
                multiproc.archive_dead_process(pid, directory)
                sizes.append(multiproc.directory_bytes(directory))
            names = sorted(os.listdir(directory))
            self.assertEqual(
                names,
                sorted(
                    [
                        ".archive.lock",
                        "counter_archive.db",
                        "histogram_archive.db",
                        "gauge_mostrecent_archive.db",
                    ]
                    + [
                        f"{typ}_{pid}.db"
                        for pid in live
                        for typ in ("counter", "histogram", "gauge_livesum")
                    ]
                ),
            )
            registry = collect(directory)
            self.assertEqual(before, 3.0 * (PIDS + len(live)))
            self.assertEqual(
                registry.get_sample_value("hits_total", {"a": "x"}),
                3.0 * (PIDS + len(live)),
            )
            self.assertEqual(registry.get_sample_value("live"), 2.0)
            self.assertLessEqual(max(sizes[PIDS // 2 :]), max(sizes[:10]) * 2)

    def test_the_total_never_decreases_while_processes_are_archived(self):
        with tempfile.TemporaryDirectory() as directory:
            pids = list(range(2000, 2040))
            self.fill(directory, pids)
            seen = []
            for pid in pids:
                seen.append(
                    collect(directory).get_sample_value("hits_total", {"a": "x"})
                )
                multiproc.archive_dead_process(pid, directory)
            seen.append(collect(directory).get_sample_value("hits_total", {"a": "x"}))
            self.assertEqual(seen, [3.0 * len(pids)] * len(seen))

    def test_histogram_buckets_sum_and_count_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            pids = list(range(3000, 3060))
            self.fill(directory, pids)
            expected = collect(directory)
            for pid in pids:
                multiproc.archive_dead_process(pid, directory)
            actual = collect(directory)
            for bucket in BUCKETS:
                labels = {"route": "home", "le": bucket}
                self.assertEqual(
                    actual.get_sample_value("lat_bucket", labels),
                    expected.get_sample_value("lat_bucket", labels),
                )
            for name in ("lat_sum", "lat_count"):
                self.assertEqual(
                    actual.get_sample_value(name, {"route": "home"}),
                    expected.get_sample_value(name, {"route": "home"}),
                )
            self.assertEqual(
                actual.get_sample_value("lat_sum", {"route": "home"}), 30.0
            )

    def test_mostrecent_gauge_keeps_the_newest_value_of_a_dead_process(self):
        key = mmap_key("snap", "snap", [], [], "Snapshot.")
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "gauge_mostrecent_1.db", [(key, 7.0, 100.0)])
            write(directory, "gauge_mostrecent_2.db", [(key, 9.0, 200.0)])
            multiproc.archive_dead_process(2, directory)
            multiproc.archive_dead_process(1, directory)
            self.assertEqual(collect(directory).get_sample_value("snap"), 9.0)

    def test_the_directory_size_gauge_is_updated_on_each_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            self.fill(directory, [7])
            multiproc.archive_dead_process(7, directory)
            value = collect(directory).get_sample_value(multiproc.DIR_BYTES_NAME)
            self.assertGreater(value, 0)
            self.assertEqual(value, multiproc.directory_bytes(directory))

    def test_an_unknown_pid_is_a_no_op(self):
        with tempfile.TemporaryDirectory() as directory:
            multiproc.archive_dead_process(99, directory)
            self.assertEqual(collect(directory).get_sample_value("hits_total"), None)

    def test_without_a_directory_nothing_happens(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            multiproc.archive_dead_process(1)

    def test_a_summary_file_is_summed(self):
        key = mmap_key("dur", "dur_count", [], [], "Duration.")
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "summary_1.db", [(key, 2.0, 0.0)])
            write(directory, "summary_2.db", [(key, 3.0, 0.0)])
            multiproc.archive_dead_process(1, directory)
            multiproc.archive_dead_process(2, directory)
            self.assertEqual(
                glob.glob(os.path.join(directory, "summary_*.db")),
                [os.path.join(directory, "summary_archive.db")],
            )
            self.assertEqual(collect(directory).get_sample_value("dur_count"), 5.0)
