/* OMEGA-X native CPU kernels and bounded single-producer/single-consumer queue.
 * SPDX-License-Identifier: MIT. SPSC is NOT safe for multiple writers/readers.
 */
#include <stddef.h>
#include <stdint.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#if defined(__x86_64__) || defined(__i386__)
#include <immintrin.h>
#define OX_X86 1
#else
#define OX_X86 0
#endif

struct ox_queue {
    _Alignas(64) _Atomic size_t head;
    _Alignas(64) _Atomic size_t tail;
    size_t mask;
    uint64_t values[];
};

struct ox_queue *ox_queue_create(size_t capacity) {
    if (capacity < 2 || capacity > (1u << 20) || (capacity & (capacity - 1))) return NULL;
    if (capacity > (SIZE_MAX - sizeof(struct ox_queue)) / sizeof(uint64_t)) return NULL;
    size_t bytes = sizeof(struct ox_queue) + capacity * sizeof(uint64_t);
    size_t aligned_bytes = (bytes + 63u) & ~(size_t)63u;
    struct ox_queue *q = aligned_alloc(64, aligned_bytes);
    if (!q) return NULL;
    memset(q, 0, aligned_bytes);
    atomic_init(&q->head, 0);
    atomic_init(&q->tail, 0);
    q->mask = capacity - 1;
    return q;
}
void ox_queue_destroy(struct ox_queue *q) { free(q); }
int ox_queue_push(struct ox_queue *q, uint64_t value) {
    if (!q) return -1;
    size_t head = atomic_load_explicit(&q->head, memory_order_relaxed);
    size_t tail = atomic_load_explicit(&q->tail, memory_order_acquire);
    if (head - tail >= q->mask + 1) return 0;
    q->values[head & q->mask] = value;
    atomic_store_explicit(&q->head, head + 1, memory_order_release);
    return 1;
}
int ox_queue_pop(struct ox_queue *q, uint64_t *out) {
    if (!q || !out) return -1;
    size_t tail = atomic_load_explicit(&q->tail, memory_order_relaxed);
    size_t head = atomic_load_explicit(&q->head, memory_order_acquire);
    if (tail == head) return 0;
    *out = q->values[tail & q->mask];
    atomic_store_explicit(&q->tail, tail + 1, memory_order_release);
    return 1;
}
size_t ox_queue_size(struct ox_queue *q) {
    if (!q) return 0;
    size_t h = atomic_load_explicit(&q->head, memory_order_acquire);
    size_t t = atomic_load_explicit(&q->tail, memory_order_acquire);
    return h - t;
}

#if defined(__GNUC__) && !defined(__clang__)
__attribute__((optimize("no-tree-vectorize")))
#endif
static void saxpy_scalar(const float *x, const float *y, float *out, size_t n, float a) {
    for (size_t i=0; i<n; ++i) out[i] = a * x[i] + y[i];
}
#if OX_X86 && defined(__GNUC__)
__attribute__((target("avx2")))
static void saxpy_avx2(const float *x, const float *y, float *out, size_t n, float a) {
    size_t i = 0;
    __m256 av = _mm256_set1_ps(a);
    for (; i + 8 <= n; i += 8) {
        __m256 xv = _mm256_loadu_ps(x + i), yv = _mm256_loadu_ps(y + i);
        _mm256_storeu_ps(out + i, _mm256_add_ps(_mm256_mul_ps(av, xv), yv));
    }
    saxpy_scalar(x + i, y + i, out + i, n - i, a);
}
__attribute__((target("avx512f")))
static void saxpy_avx512(const float *x, const float *y, float *out, size_t n, float a) {
    size_t i = 0;
    __m512 av = _mm512_set1_ps(a);
    for (; i + 16 <= n; i += 16) {
        __m512 xv = _mm512_loadu_ps(x + i), yv = _mm512_loadu_ps(y + i);
        _mm512_storeu_ps(out + i, _mm512_add_ps(_mm512_mul_ps(av, xv), yv));
    }
    saxpy_scalar(x + i, y + i, out + i, n - i, a);
}
#endif
int ox_cpu_features(void) {
    int result = 0;
#if OX_X86 && defined(__GNUC__)
    __builtin_cpu_init();
    if (__builtin_cpu_supports("avx2")) result |= 1;
    if (__builtin_cpu_supports("avx512f")) result |= 2;
#endif
    return result;
}
int ox_saxpy(const float *x, const float *y, float *out, size_t n, float a, int mode) {
    if ((!x || !y || !out) && n) return -1;
    if (!isfinite(a) || n > (1u << 26) || mode < 0 || mode > 3) return -1;
    int features = ox_cpu_features();
    if (mode == 2 && !(features & 1)) return -2;
    if (mode == 3 && !(features & 2)) return -2;
#if OX_X86 && defined(__GNUC__)
    if (mode == 3 || (mode == 0 && (features & 2))) { saxpy_avx512(x,y,out,n,a); return 3; }
    if (mode == 2 || (mode == 0 && (features & 1))) { saxpy_avx2(x,y,out,n,a); return 2; }
#endif
    saxpy_scalar(x,y,out,n,a);
    return 1;
}

/* Signed INT8 GEMM with INT64 accumulators. This is a real CPU kernel, NOT NPU
 * execution. Contiguous row-major buffers, no FPU rounding, deterministic.
 * Loop interchange keeps B and C accesses contiguous within each k row.
 */
int ox_matmul_i8(const int8_t *a, const int8_t *b, int64_t *out,
                 size_t m, size_t k, size_t n) {
    if (!a || !b || !out || !m || !k || !n || m > 256 || k > 256 || n > 256)
        return -1;
    memset(out, 0, m * n * sizeof(int64_t));
    for (size_t i = 0; i < m; ++i) {
        int64_t *row = out + i * n;
        for (size_t p = 0; p < k; ++p) {
            int64_t left = (int64_t)a[i*k+p];
            const int8_t *right = b + p*n;
            for (size_t j = 0; j < n; ++j)
                row[j] += left * (int64_t)right[j];
        }
    }
    return 0;
}
