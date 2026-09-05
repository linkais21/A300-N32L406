#include "bcr.h"
#include "image_verify.h"
#include <stddef.h>
#include <string.h>

bool bcr_valid(const bcr_record_t *r)
{
    bcr_record_t c;
    if (!r || r->magic != BCR_MAGIC || r->commit_marker != BCR_COMMIT_MARKER) return false;
    c=*r; c.crc32=0U; c.commit_marker=0xFFFFFFFFUL;
    return image_crc32(&c,(uint32_t)offsetof(bcr_record_t,crc32)) == r->crc32;
}

static bool sequence_newer(uint32_t a, uint32_t b)
{
    return (int32_t)(a - b) > 0;
}

bool bcr_load(bcr_record_t *out)
{
    bcr_record_t a,b; bool va=boot_bcr_read(BCR_SLOT_A_ADDR,&a,sizeof a)&&bcr_valid(&a); bool vb=boot_bcr_read(BCR_SLOT_B_ADDR,&b,sizeof b)&&bcr_valid(&b);
    if (!out || (!va && !vb)) return false;
    *out = (!vb || (va && sequence_newer(a.sequence,b.sequence))) ? a : b;
    return true;
}

bool bcr_commit(const bcr_record_t *record)
{
    bcr_record_t r; bcr_record_t current; uint32_t addr;
    if (!record) return false;
    r=*record;
    r.magic=BCR_MAGIC;
    r.commit_marker=0xFFFFFFFFUL;
    r.crc32=0U;
    r.crc32=image_crc32(&r,(uint32_t)offsetof(bcr_record_t,crc32));
    addr = BCR_SLOT_A_ADDR;
    if (bcr_load(&current)) addr = (current.sequence & 1U) ? BCR_SLOT_B_ADDR : BCR_SLOT_A_ADDR;
    if (!boot_bcr_erase(addr)) return false;
    if (!boot_bcr_write(addr,&r,(uint32_t)offsetof(bcr_record_t,commit_marker))) return false;
    uint32_t marker=BCR_COMMIT_MARKER;
    if (!boot_bcr_write(addr+offsetof(bcr_record_t,commit_marker),&marker,sizeof marker)) return false;
    return boot_bcr_readback(addr,&r,(uint32_t)offsetof(bcr_record_t,commit_marker)) && boot_bcr_readback(addr+offsetof(bcr_record_t,commit_marker),&marker,sizeof marker);
}

bool bcr_mark_trial_healthy(void)
{
    bcr_record_t r;
    if (!bcr_load(&r) || r.state != BCR_TRIAL) return false;
    r.state = BCR_ACTIVE; r.boot_attempts = 0U; r.rollback_floor = r.image_version; ++r.sequence;
    return bcr_commit(&r);
}

void bcr_note_trial_reset(bool fault_or_watchdog)
{
    bcr_record_t r;
    if (!fault_or_watchdog || !bcr_load(&r) || r.state != BCR_TRIAL) return;
    if (r.boot_attempts < 0xFFU) ++r.boot_attempts;
    if (r.boot_attempts >= 3U) r.state=BCR_ROLLBACK;
    ++r.sequence;
    (void)bcr_commit(&r);
}
