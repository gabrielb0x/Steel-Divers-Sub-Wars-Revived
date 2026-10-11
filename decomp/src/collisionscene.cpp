// source/collisionscene.cpp (collisionscene.o): which actors may touch, and the collisions of a frame. The
// world owns one CollisionScene (World +collisionScene); World::update calls updateActors when actors
// changed, then processCollisions every frame. Each collision found goes to both actors
// (Actor::addCollResult) and, through them, to their scripts' @eventCollide(other, point, normal...).
//
// Reconstructed by hand from decomp/raw/source/collisionscene.cpp and the disassembly. Not compilable on its own.
//
// Two actors are a pair when both are active, not idle, have collision shapes, and one's collisionMask
// (+0x10, actorSetCollisionCheck) matches the other's type (+0x0C, actorSetCollisionType).

struct CollisionPair {                  // 0x10 bytes
	Actor *a, *b;
	CollisionPair *next, *prev;         // the list of pairs (sorted by address) or of free pairs
};

class CollisionScene {
	CollisionPair pairs[0x1000];        // +0x00000
	CollisionPair *free;                // +0x10000
	CollisionPair *used;                // +0x10004
	u8 *dirty;                          // +0x10008 261 flags: actors whose pairs must be rebuilt
};

// 0x001095C8: every pair free (a list through `next`), no pair used.
void CollisionScene::init()
{
	free = &pairs[0];
	used = nullptr;
	for (int i = 0; i < 0x1000 - 1; i++)
		pairs[i].next = &pairs[i + 1];
	pairs[0x1000 - 1].next = nullptr;
	dirty = (u8 *)alloc(0x105);
	memset(dirty, 0, 0x105);
}

// 0x0024DC68: an actor appeared, changed its type or mask, or went idle (World::setActorCollisionStateDirty).
void CollisionScene::setActorDirty(int actor) { dirty[actor] = 1; }

// 0x001091F4: the pairs of the dirty actors are dropped, then made again against every actor (a pair of two
// dirty actors only once). The used list stays sorted by the pairs' addresses.
void CollisionScene::updateActors()
{
	int count = g_world->actorCount;
	for (int i = 0; i < count; i++) {
		if (!dirty[i])
			continue;
		Actor *actor = g_world->getActor(i);
		for (CollisionPair *p = used, *next; p != nullptr; p = next) {
			next = p->next;
			if (p->a == actor || p->b == actor)
				release(p);                     // unlinked, onto the free list
		}
	}
	for (int i = 0; i < count; i++) {
		Actor *a = g_world->actors[i];
		if (!dirty[i] || !a->active || a->idle || a->collShapeCount == 0 || (a->collisionMask == 0 && a->typeMask == 0))
			continue;
		for (int j = 0; j < count; j++) {
			Actor *b = g_world->actors[j];
			if (j == i || (j < i && dirty[j]) || !b->active || b->idle || b->collShapeCount == 0)
				continue;
			if (!(a->collisionMask & b->typeMask) && !(b->collisionMask & a->typeMask))
				continue;
			CollisionPair *p = take();          // the first free pair, inserted in address order. With none
			p->a = a;                           // left (4,095 pairs), these two writes go through a null
			p->b = b;                           // pointer: nothing guards them
		}
	}
	memset(dirty, 0, 0x105);
}

// 0x0010941C: for each pair and each shape of both actors, a cheap test on the shapes' bounding spheres
// (centre = the actor's simulated position + the shape's offset, +0x04; radius +0x1C), then the exact test
// (the shape's intersect, vtable +0x04, which dispatches on the other shape's kind). A hit goes to each
// actor that has a type, with the other's velocity in it.
void CollisionScene::processCollisions()
{
	for (CollisionPair *p = used; p != nullptr; p = p->next) {
		for (int j = 0; j < p->b->collShapeCount; j++) {
			CollShape *sb = p->b->collShapes[j];
			for (int i = 0; i < p->a->collShapeCount; i++) {
				CollShape *sa = p->a->collShapes[i];
				VEC3 d = (VEC3(p->a->positionPtr) + sa->offset) - (VEC3(p->b->positionPtr) + sb->offset);
				f32 reach = sa->boundingRadius + sb->boundingRadius;
				if (dot(d, d) >= reach * reach)
					continue;
				CollResult r;
				r.reset();
				r.actorA = p->a;
				r.actorB = p->b;
				if (!sa->intersect(sb, &r))
					continue;
				if (r.swapped)
					r.swap();
				if (p->b->typeMask != 0) {
					r.otherVelocity = VEC3(p->b->velocity);
					p->a->addCollResult(&r);
				}
				r.swap();
				if (p->a->typeMask != 0) {
					r.otherVelocity = VEC3(p->a->velocity);
					p->b->addCollResult(&r);
				}
			}
		}
	}
}

// game/actor.cpp, 0x00116968: Actor::addCollResult keeps one collision per other actor (the result's word
// +0x2C), the one whose first float is the smallest, for 8 other actors at most per frame (ActorData +0x1020,
// 0x38 bytes each; Actor +0xF4 counts them).
