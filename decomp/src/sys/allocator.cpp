// source/sys/allocator.cpp (allocator.o): the game's heaps, each an nn::fnd::ExpHeap with a name and a
// "group" (the ExpHeap's group id, 0..255) under which blocks are allocated, so that a whole group can be
// freed or measured at once.
//
// Reconstructed by hand from decomp/raw/source/sys/allocator.cpp and the disassembly. Not compilable on its
// own. The global allocator (operator new, allocAligned) is *(Allocator **)0x0038EC00.

class Allocator {                       // vtable 0x00376B68
	nn::fnd::ExpHeapBase heap;          // +0x04
	char name[32];                      // +0x5C (for the out-of-memory log)
	u32 group;                          // +0x7C
	// ... up to +0x1ED4 (+0x1ED0 cleared by init)
};

// 0x0010DE64
void Allocator::init(void *start, u32 size, const char *name)
{
	heap.Initialize(start, size, 0x100);
	strcpy(this->name, name);
	group = 0;
	field_1ED0 = 0;
}

void Allocator::setGroup(u32 group) { this->group = group; }   // 0x0010DEA0

// 0x0024D6A4 (Allocator::Alloc 0x0024D6A0 runs into it): group 0 allocates from the end of the heap, any
// other group from its start (a negative alignment, for nn::fnd). Alignments above 128 are done by hand:
// size + alignment, rounded up. Failure: "[Allocator::AllocAligned] %s out of memory, attempting to
// allocate %d bytes (%f kb, %f mb)", and null.
void *Allocator::AllocAligned(u32 size, int alignment)
{
	if (alignment <= 0x80)
		return heap.Allocate(size, group == 0 ? -alignment : alignment, group, 0, 0);
	u8 *block = (u8 *)heap.Allocate(size + alignment, group == 0 ? -4 : 4, group, 1, 0);
	return (void *)((u32)(block + alignment - 1) & ~(alignment - 1));
}

// 0x0023EEB0: runs into ExpHeapBase::Free.
void Allocator::Free(void *block) { heap.Free(block); }

// 0x0024DC44 / 0x00110DEC: frees every block of a group.
void Allocator::freeGroup(u32 group)
{
	heap.VisitAllBlocks([](void *block, nn::fnd::ExpHeapBase *heap, u32 group) {
		if (nn::fnd::detail::GetGroupIDForMBlockHeap(block) == group)
			heap->Free(block);
	}, group);
}

// 0x002F4F58 / 0x00175100: the bytes a group uses (a static total, 0x0038E908).
u32 Allocator::getSizeOfGroup(u32 group)
{
	static u32 total;
	total = 0;
	heap.VisitAllBlocks([](void *block, nn::fnd::ExpHeapBase *heap, u32 group) {
		if (nn::fnd::detail::GetGroupIDForMBlockHeap(block) == group)
			total += heap->GetSizeOf(block);
	}, group);
	return total;
}

// 0x002F4F98: the destructor.
Allocator::~Allocator() { heap.Finalize(); }

// AllocatorHybrid (vtable 0x00376524, 0x00109694): an nn::fnd::IAllocator that forwards to an Allocator,
// for the SDK's libraries.
void *AllocatorHybrid::Allocate(u32 size, int alignment) { return target->AllocAligned(size, (u8)alignment); }  // 0x0017FAE8
void AllocatorHybrid::Free(void *block) { target->Free(block); }                                           // 0x0017FAD8 (vtable +0x0C)
