import random
import unittest

from src.services.music_queue import MusicQueue, QueueFullError


class MusicQueueTests(unittest.TestCase):
    def test_extend_is_atomic_when_capacity_is_exceeded(self):
        queue = MusicQueue[str](max_size=3)
        queue.extend(["a", "b"])

        with self.assertRaises(QueueFullError) as context:
            queue.extend(["c", "d"])

        self.assertEqual(queue.snapshot(), ["a", "b"])
        self.assertEqual(context.exception.available, 1)

    def test_remove_uses_one_based_position(self):
        queue = MusicQueue[str](max_size=5)
        queue.extend(["a", "b", "c"])

        self.assertEqual(queue.remove(2), "b")
        self.assertEqual(queue.snapshot(), ["a", "c"])
        with self.assertRaises(IndexError):
            queue.remove(3)

    def test_shuffle_preserves_every_item(self):
        queue = MusicQueue[int](max_size=5)
        queue.extend([1, 2, 3, 4, 5])

        queue.shuffle(random.Random(7))

        self.assertEqual(sorted(queue.snapshot()), [1, 2, 3, 4, 5])
        self.assertNotEqual(queue.snapshot(), [1, 2, 3, 4, 5])

    def test_clear_returns_removed_count(self):
        queue = MusicQueue[int](max_size=3)
        queue.extend([1, 2, 3])

        self.assertEqual(queue.clear(), 3)
        self.assertFalse(queue)
        self.assertEqual(queue.available, 3)


if __name__ == "__main__":
    unittest.main()
