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

from __future__ import division

__all__ = "Bitmap"

import array
import bisect
import copy
import io
import struct

MAGIC_NUMBER = 12348
STORAGE_VERSION = 0
COOKIE = MAGIC_NUMBER + (STORAGE_VERSION << 16)
HEADER_BASE_SIZE = 8
ARRAY_MAX_SIZE = 4096
BITMAP_N = (1 << 16) // 64
RUN_MAX_SIZE = 2048


class Bitmap(object):

    __slots__ = "containers"

    def __init__(self):
        self.containers = SliceContainers()

    def add(self, bit):
        container = self.containers.get_or_create(bit >> 16)
        container.add(bit & 0xFFFF)

    def __iter__(self):
        return self.containers.__iter__()

    def write_to(self, writer, optimize=True):
        return self.containers.write_to(writer, optimize)


class Container(object):

    __slots__ = "array", "bitmap", "runs", "type", "n"

    TYPE_ARRAY = 1
    TYPE_BITMAP = 2
    TYPE_RLE = 3

    SERIALIZATION_COST_MAP = {
        TYPE_ARRAY: lambda c: 8 * len(c.array),
        TYPE_BITMAP: lambda c: 8 * len([x for x in c.bitmap if x]),
        TYPE_RLE: lambda c: 16 * len(c.runs) + 2,
    }

    def __init__(self):
        self.type = self.TYPE_ARRAY
        self.array = []
        self.bitmap = []
        self.runs = []
        self.n = 0

    def add(self, bit):
        if self.type == self.TYPE_BITMAP:
            return self._bitmap_add(bit)
        n = self.n
        index = bisect.bisect_left(self.array, bit)
        # Exit if the bit exists
        if index != n and bit == self.array[index]:
            return
        # Convert to a bitmap container if too many values are in an array container.
        if n >= ARRAY_MAX_SIZE - 1:
            self._convert_to_bitmap()
            return self._bitmap_add(bit)

        # Otherwise insert into array.
        self.n += 1
        bisect.insort_left(self.array, bit)

    def __iter__(self):
        if self.type == self.TYPE_ARRAY:
            for bit in self.array:
                yield bit
        elif self.type == self.TYPE_BITMAP:
            power_range = range(64)
            for key, value in enumerate(self.bitmap):
                if not value:
                    continue
                for i in power_range:
                    v = 2**i
                    if value & v == v:
                        yield key * 64 + i
        elif self.type == self.TYPE_RLE:
            try:
                arange = xrange
            except NameError:
                # Python 3
                arange = range
            for start, last in self.runs:
                for bit in arange(start, last + 1):
                    yield bit
        else:
            raise Exception("Invalid container type: " % self.type)

    def _copy(self):
        return copy.copy(self)

    def _convert_to_bitmap(self):
        # converts from array to bitmap
        if self.type == self.TYPE_BITMAP:
            return
        self.type = self.TYPE_BITMAP
        # we can move this part to to_bitmap function to
        # support converting from runs
        bitmap = [0] * BITMAP_N
        for bit in self.array:
            bitmap[bit // 64] |= 1 << (bit % 64)
        self.bitmap = bitmap
        self.array = []

    def _bitmap_add(self, bit):
        if (self.bitmap[bit // 64] & (1 << (bit % 64))):
            return
        self.n += 1
        self.bitmap[bit // 64] |= (1 << (bit % 64))

    def _convert_to_runs(self):
        if self.type == self.TYPE_RLE:
            return
        runs = to_runs(self.__iter__())
        if len(runs) > RUN_MAX_SIZE:
            return
        self.runs = runs
        self.type = self.TYPE_RLE
        self.array = []
        self.bitmap = []

    def __lt__(self, other):
        # required for Python 3
        return False

    def __len__(self):
        return self.n

    def write_to(self, writer):
        if self.type == self.TYPE_ARRAY:
            arr = array.array("H", self.array)
            return writer.write(arr.tostring())
        elif self.type == self.TYPE_BITMAP:
            ba = bytearray(8 * len(self.bitmap))
            for i, item in enumerate(self.bitmap):
                struct.pack_into("<Q", ba, i * 8, item)
            return writer.write(ba)
        elif self.type == self.TYPE_RLE:
            written = writer.write(struct.pack("<H", len(self.runs)))
            for start, last in self.runs:
                written += writer.write(struct.pack("<HH", start, last))
            return written
        else:
            raise Exception("Invalid container type: " % self.type)

    def _serialization_cost(self):
        try:
            return self.SERIALIZATION_COST_MAP[self.type](self)
        except KeyError:
            raise Exception("Invalid container type: " % self.type)

    def _optimized(self):
        self_copy = self._copy()
        self_copy._convert_to_runs()
        if self_copy._serialization_cost() < self._serialization_cost():
            return self_copy
        self_copy = None
        return self


def to_runs(gen):
    runs = []
    try:
        start = last = next(gen)
    except StopIteration:
        return []
    for bit in gen:
        if bit == last + 1:
            last = bit
        else:
            runs.append((start, last))
            start = last = bit
    runs.append((start, last))
    return runs


class SliceContainers(object):

    __slots__ = "key_containers", "last_key", "last_container"
    _empty_container = Container()

    def __init__(self):
        self.key_containers = []
        self.last_key = 0
        self.last_container = None

    def put_container(self, key, container):
        bisect.insort(self.key_containers, (key, container))

    def get_container(self, key):
        key_containers = self.key_containers
        index = bisect.bisect_left(key_containers, (key, self._empty_container))
        if index != len(key_containers):
            key2, container = key_containers[index]
            if key == key2:
                return container
        return None

    def get_or_create(self, key):
        if key == self.last_key and self.last_container != None:
            return self.last_container
        self.last_key = key
        container = self.get_container(key)
        if not container:
            container = Container()
            self.put_container(key, container)
        self.last_container = container
        return container

    def __iter__(self):
        for key, container in self.key_containers:
            for bit in container:
                yield (key << 16) + bit

    def write_to(self, writer, optimize=True):
        container_count = sum(1 for k, c in self.key_containers if len(c) > 0)

        # write header
        writer.write(struct.pack("<I", COOKIE))
        writer.write(struct.pack("<I", container_count))

        # write container meta
        containers = []
        for key, container in self.key_containers:
            bit_count = len(container)
            if bit_count < 1:
                continue
            if optimize:
                container = container._optimized()
            containers.append(container)
            writer.write(struct.pack("<Q", key))
            writer.write(struct.pack("<H", container.type))
            writer.write(struct.pack("<H", bit_count - 1))

        # write container data
        data = io.BytesIO()
        offset = HEADER_BASE_SIZE + container_count * (8 + 2 + 2 + 4)
        for container in containers:
            writer.write(struct.pack("<I", offset))
            size = container.write_to(data)
            offset += size

        writer.write(data.getvalue())
        return offset
