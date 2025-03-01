import os
import time
import Queue

from lutris.util import http, jobs
from lutris.util.log import logger


class Downloader():
    """Non-blocking downloader.

    Do start() then check_progress() at regular intervals.
    Download is done when check_progress() returns 1.0.
    Stop with cancel().
    """
    def __init__(self, url, dest, overwrite=False):
        self.url = url
        self.dest = dest
        self.overwrite = overwrite
        self.file_pointer = None

        # Read these after a check_progress()
        self.downloaded_size = 0  # Bytes
        self.full_size = 0  # Bytes
        self.progress_fraction = 0
        self.progress_percentage = 0
        self.speed = 0
        self.average_speed = 0
        self.time_left = '00:00:00'  # Based on average speed

        self.last_check_time = 0
        self.last_speeds = []
        self.speed_check_time = 0
        self.time_left_check_time = 0

        self.cancelled = False
        self.queue = Queue.Queue()

    def start(self):
        """Start download job."""
        logger.debug("Starting download of:\n " + self.url)
        self.last_check_time = time.time()
        if self.overwrite and os.path.isfile(self.dest):
            os.remove(self.dest)
        self.file_pointer = open(self.dest, 'wb')
        self.thread = jobs.AsyncCall(self.async_download, self.on_done,
                                     self.url, self.queue, stoppable=True)

    def check_progress(self):
        """Append last downloaded chunk to dest file and store stats.

        :return: progress (between 0.0 and 1.0)"""
        if not self.queue.qsize() or self.cancelled:
            return self.progress_fraction

        downloaded_size, full_size = self.write_queue()
        self.get_stats(downloaded_size, full_size)

        return self.progress_fraction

    def cancel(self):
        """Request download stop and remove destination file."""
        logger.debug("Download cancelled")
        self.thread.stop_request.set()
        self.cancelled = True
        if os.path.isfile(self.dest):
            os.remove(self.dest)

    def on_done(self, request, error):
        if self.cancelled:
            self.file_pointer.close()
            return
        logger.debug("Download finished")
        while self.queue.qsize():
            self.check_progress()
        if not self.full_size and self.downloaded_size:
            self.progress_fraction = 1.0
            self.progress_percentage = 100
        self.file_pointer.close()

    def async_download(self, url, queue, stop_request=None):
        request = http.Request(url, stop_request=stop_request,
                               thread_queue=queue)
        return request.get()

    def write_queue(self):
        """Append download queue to destination file."""
        buffered_chunk = ''
        while self.queue.qsize():
            chunk, received_bytes, total_bytes = self.queue.get()
            buffered_chunk += chunk

        if buffered_chunk:
            self.file_pointer.write(buffered_chunk)

        return received_bytes, total_bytes

    def get_stats(self, downloaded_size, full_size):
        """Calculate and store download stats."""
        self.last_size = self.downloaded_size
        self.downloaded_size = downloaded_size
        self.full_size = full_size
        self.speed, self.average_speed = self.get_speed()
        self.time_left = self.get_average_time_left()
        self.last_check_time = time.time()

        if self.full_size:
            self.progress_fraction = (
                float(self.downloaded_size) / float(self.full_size)
            )
            self.progress_percentage = self.progress_fraction * 100

    def get_speed(self):
        """Return (speed, average speed) tuple."""
        elapsed_time = time.time() - self.last_check_time
        chunk_size = self.downloaded_size - self.last_size
        speed = chunk_size / elapsed_time or 1
        self.last_speeds.append(speed)

        # Average speed
        if time.time() - self.speed_check_time < 1:  # Minimum delay
            return self.speed, self.average_speed

        sample_size = 20
        while len(self.last_speeds) > sample_size:
            self.last_speeds.pop(0)

        sample = self.last_speeds
        if len(sample) > 7:
            # Skim extreme values
            sample.pop()
            sample.pop()
            sample.pop(0)
            sample.pop(0)

        added_speeds = 0
        for speed in sample:
            added_speeds += speed
        average_speed = added_speeds / len(sample)

        self.speed_check_time = time.time()
        return speed, average_speed

    def get_average_time_left(self):
        """Return average download time left as string."""
        if not self.full_size:
            return '???'

        elapsed_time = time.time() - self.time_left_check_time
        if elapsed_time < 1:  # Minimum delay
            return self.time_left

        average_time_left = (
            (self.full_size - self.downloaded_size) / self.average_speed
        )
        m, s = divmod(average_time_left, 60)
        h, m = divmod(m, 60)
        self.time_left_check_time = time.time()
        return '%d:%02d:%02d' % (h, m, s)
