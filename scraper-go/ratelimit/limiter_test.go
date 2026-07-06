package ratelimit

import (
	"context"
	"errors"
	"testing"
	"time"
)

func TestLimiterAcquireCanceledDuringIntervalWait(t *testing.T) {
	limiter := New(time.Hour, 0)

	if err := limiter.Acquire(context.Background()); err != nil {
		t.Fatalf("initial acquire failed: %v", err)
	}

	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	err := limiter.Acquire(ctx)
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("expected context.Canceled, got %v", err)
	}
}

func TestSimpleLimiterAcquireCanceledDuringIntervalWait(t *testing.T) {
	limiter := NewSimple(time.Hour)

	if err := limiter.Acquire(context.Background()); err != nil {
		t.Fatalf("initial acquire failed: %v", err)
	}

	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	err := limiter.Acquire(ctx)
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("expected context.Canceled, got %v", err)
	}
}

// TestBanNoProberFallback verifies that without a prober, waitBan
// waits the full ban duration (using a very short duration).
func TestBanNoProberFallback(t *testing.T) {
	limiter := New(0, 0)
	limiter.SetBan(100 * time.Millisecond)

	if !limiter.IsBanned() {
		t.Fatal("expected to be banned after SetBan")
	}

	start := time.Now()
	err := limiter.Acquire(context.Background())
	elapsed := time.Since(start)

	if err != nil {
		t.Fatalf("Acquire failed: %v", err)
	}
	if elapsed < 90*time.Millisecond {
		t.Fatalf("expected to wait ~100ms, only waited %v", elapsed)
	}
	if limiter.IsBanned() {
		t.Fatal("expected ban to be cleared after waiting")
	}
}

// TestClearBan verifies that ClearBan removes the ban immediately.
func TestClearBan(t *testing.T) {
	limiter := New(0, 0)
	limiter.SetBan(1 * time.Hour)

	if !limiter.IsBanned() {
		t.Fatal("expected to be banned")
	}

	limiter.ClearBan()

	if limiter.IsBanned() {
		t.Fatal("expected ban to be cleared")
	}
}
