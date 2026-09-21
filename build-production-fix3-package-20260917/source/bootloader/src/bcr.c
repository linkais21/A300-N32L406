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

static bool record_erased(const bcr_record_t *record)
{
    const uint8_t *bytes = (const uint8_t *)record;
    for (uint32_t i = 0U; i < (uint32_t)sizeof(*record); ++i)
        if (bytes[i] != 0xFFU) return false;
    return true;
}

bcr_load_result_t bcr_load(bcr_record_t *out)
{
    bcr_record_t a,b;
    bool read_a=false,read_b=false,va=false,vb=false;
    if (!out) return BCR_LOAD_IO_ERROR;
    /* A tight retry can repeat the same cold-start zero read. Re-read BOTH
     * slots after a watchdog-serviced settling interval, including I/O errors.
     * Never use a readable older slot while the other slot is unreadable. */
    for (unsigned attempt = 0U; attempt < 20U; ++attempt) {
        read_a = boot_bcr_read(BCR_SLOT_A_ADDR,&a,sizeof a);
        read_b = boot_bcr_read(BCR_SLOT_B_ADDR,&b,sizeof b);
        if (read_a && read_b) {
            va=bcr_valid(&a); vb=bcr_valid(&b);
            if (va || vb || (record_erased(&a) && record_erased(&b))) break;
        }
        if (attempt == 19U)
            return (!read_a || !read_b) ? BCR_LOAD_IO_ERROR : BCR_LOAD_INVALID;
        boot_bcr_retry_wait(attempt + 1U, !read_a || !read_b);
    }
    /* An unreadable slot can contain a newer Pending record. */
    if (!read_a || !read_b) return BCR_LOAD_IO_ERROR;
    if (!va && !vb)
        return record_erased(&a) && record_erased(&b) ?
               BCR_LOAD_ABSENT : BCR_LOAD_INVALID;
    *out = (!vb || (va && sequence_newer(a.sequence,b.sequence))) ? a : b;
    return BCR_LOAD_FOUND;
}

bool bcr_commit(const bcr_record_t *record)
{
    bcr_record_t r; bcr_record_t a, b; bool va, vb, read_a, read_b; uint32_t addr;
    if (!record) return false;
    r=*record;
    r.magic=BCR_MAGIC;
    r.commit_marker=0xFFFFFFFFUL;
    r.crc32=0U;
    r.crc32=image_crc32(&r,(uint32_t)offsetof(bcr_record_t,crc32));
    /* Select the slot opposite the physically newest valid record.  Sequence
     * parity is not a slot identity: recovery from a torn write or a legacy
     * record can leave an even sequence in slot A (or odd in slot B). */
    read_a = boot_bcr_read(BCR_SLOT_A_ADDR, &a, sizeof a);
    read_b = boot_bcr_read(BCR_SLOT_B_ADDR, &b, sizeof b);
    if (!read_a || !read_b) return false;
    va = bcr_valid(&a);
    vb = bcr_valid(&b);
    if (!va && !vb) addr = (r.sequence & 1U) ? BCR_SLOT_B_ADDR : BCR_SLOT_A_ADDR;
    else if (!va) addr = BCR_SLOT_A_ADDR;
    else if (!vb) addr = BCR_SLOT_B_ADDR;
    else addr = ((int32_t)(a.sequence - b.sequence) > 0) ? BCR_SLOT_B_ADDR : BCR_SLOT_A_ADDR;
    if (!boot_bcr_erase(addr)) return false;
    if (!boot_bcr_write(addr,&r,(uint32_t)offsetof(bcr_record_t,commit_marker))) return false;
    uint32_t marker=BCR_COMMIT_MARKER;
    if (!boot_bcr_write(addr+offsetof(bcr_record_t,commit_marker),&marker,sizeof marker)) return false;
    return boot_bcr_readback(addr,&r,(uint32_t)offsetof(bcr_record_t,commit_marker)) && boot_bcr_readback(addr+offsetof(bcr_record_t,commit_marker),&marker,sizeof marker);
}

bool bcr_mark_trial_healthy(void)
{
    bcr_record_t r;
    if (bcr_load(&r) != BCR_LOAD_FOUND || r.state != BCR_TRIAL) return false;
    r.state = BCR_ACTIVE; r.boot_attempts = 0U; ++r.sequence;
    return bcr_commit(&r);
}

bool bcr_note_trial_reset(bool fault_or_watchdog)
{
    bcr_record_t r;
    bcr_load_result_t loaded;
    if (!fault_or_watchdog) return true;
    loaded = bcr_load(&r);
    if (loaded == BCR_LOAD_ABSENT) return true;
    if (loaded != BCR_LOAD_FOUND) return false;
    if (r.state != BCR_TRIAL) return true;
    if (r.boot_attempts < 0xFFU) ++r.boot_attempts;
    if (r.boot_attempts >= 3U) r.state=BCR_ROLLBACK;
    ++r.sequence;
    return bcr_commit(&r);
}
