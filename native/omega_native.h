#ifndef OMEGA_X_NATIVE_H
#define OMEGA_X_NATIVE_H
#include <stddef.h>
#include <stdint.h>
struct ox_queue;
struct ox_queue *ox_queue_create(size_t capacity);
void ox_queue_destroy(struct ox_queue *q);
int ox_queue_push(struct ox_queue *q, uint64_t value);
int ox_queue_pop(struct ox_queue *q, uint64_t *out);
size_t ox_queue_size(struct ox_queue *q);
int ox_cpu_features(void);
int ox_saxpy(const float *x, const float *y, float *out, size_t n, float a, int mode);
int ox_matmul_i8(const int8_t *a, const int8_t *b, int64_t *out, size_t m, size_t k, size_t n);
#endif
