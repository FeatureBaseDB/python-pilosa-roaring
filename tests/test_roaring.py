# Copyright 2018 Pilosa Corp.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
# 1. Redistributions of source code must retain the above copyright
# notice, this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution.
#
# 3. Neither the name of the copyright holder nor the names of its
# contributors may be used to endorse or promote products derived
# from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND
# CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES,
# INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
# WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH
# DAMAGE.
#

import sys
import os
sys.path.insert(0, os.path.split(os.path.dirname(os.path.abspath(__file__)))[0])

import unittest

from roaring.roaring import Container, SliceContainers, Bitmap, ARRAY_MAX_SIZE

class ContainerTestCase(unittest.TestCase):

    def test_iterate(self):
        c = Container()
        c.add(10)
        target = [10]
        self.assertEqual(target, list(c.iterate()))
        c.add(42)
        target = [10, 42]
        self.assertEqual(target, list(c.iterate()))
        for i in range(ARRAY_MAX_SIZE + 1):
            c.add(i)
        target = list(range(ARRAY_MAX_SIZE + 1))
        self.assertEqual(target, list(c.iterate()))
        self.assertEqual(c.type, c.TYPE_BITMAP)

    def test_iterate_invalid_container(self):
        c = Container()
        c.type = 42
        self.assertRaises(Exception, list, c.iterate)


class SliceContainersTestCase(unittest.TestCase):

    def test_put_container(self):
        sc = SliceContainers()
        sc.put_container(10, Container())
        sc.put_container(2, Container())
        sc.put_container(5, Container())
        target = [2, 5, 10]
        self.assertEqual(target, [k for k, _ in sc.key_containers])


class BitmapTestCase(unittest.TestCase):

    def test_bitmap_add(self):
        bmp = Bitmap()
        # force the underlying container to be a bitmap
        target = list(range(ARRAY_MAX_SIZE + 1))
        for i in target:
            bmp.add(i)
        self.assertEqual(target, list(bmp.iterate()))

        bmp = Bitmap()
        target = list(range(2**16))
        for i in target:
            bmp.add(i)
        bmp.add(42)  # add the same bit
        self.assertEqual(target, list(bmp.iterate()))

        bmp = Bitmap()
        target = list(range(2**32, 2**32 + 10))
        for i in target:
            bmp.add(i)
        self.assertEqual(target, list(bmp.iterate()))

        bmp = Bitmap()
        target = list(range(2**32, 2**32 + ARRAY_MAX_SIZE + 1))
        for i in target:
            bmp.add(i)
        self.assertEqual(target, list(bmp.iterate()))

        bmp = Bitmap()
        target = list(range(2**64 - 1, 2**64 -1 - ARRAY_MAX_SIZE - 1, -1))
        for i in target:
            bmp.add(i)
        target = list(reversed(target))
        self.assertEqual(target, list(bmp.iterate()))

    def test_bitmap_serialize(self):
        import io
        bmp = Bitmap()
        for i in range(ARRAY_MAX_SIZE):
            bmp.add(i)
        for i in range(2**32, 2**32 + 10):
            bmp.add(i)
        bmp.add(2**64 - 1)
        bmp.add(2**64 - 2)
        bmp.add(2**64 - 3)
        target = list(range(ARRAY_MAX_SIZE))
        target.extend(range(2**32, 2**32 + 10))
        target.append(2**64 - 3)
        target.append(2**64 - 2)
        target.append(2**64 - 1)
        self.assertEqual(target, list(bmp.iterate()))

        bio = io.BytesIO()
        written = bmp.write_to(bio)
        with open("tests/fixtures/serialized.bitmap", "rb") as f:
            target = f.read()
        self.assertEqual(target, bio.getvalue())
        self.assertEqual(8274, written)

if __name__ == "__main__":
    unittest.main()