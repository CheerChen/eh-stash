package ratelimit

import (
	"context"
	"log/slog"
	"sync"
	"time"
)

// BanProbeFunc is called during ban backoff to check if the ban is still active.
// Returns stillBanned=true if the ban page is still served.
// Returns stillBanned=false if the site responds normally (ban lifted).
// Returns err non-nil if the probe was inconclusive (timeout, connection error).
type BanProbeFunc func(ctx context.Context) (stillBanned bool, err error)

// Limiter is a global rate limiter with ban awareness.
// All main-site HTTP requests must call Acquire before proceeding.
type Limiter struct {
	mu       sync.Mutex
	interval time.Duration
	lastTime time.Time

	banMu       sync.RWMutex
	banUntil    time.Time
	banCooldown time.Duration
	banProber   BanProbeFunc
}

func New(interval time.Duration, banCooldown time.Duration) *Limiter {
	return &Limiter{
		interval:    interval,
		banCooldown: banCooldown,
	}
}

// SetBanProber registers a probe function used during ban backoff.
// If not set, waitBan falls back to waiting the full ban duration.
func (l *Limiter) SetBanProber(f BanProbeFunc) {
	l.banMu.Lock()
	defer l.banMu.Unlock()
	l.banProber = f
}

// ClearBan removes the current ban immediately.
func (l *Limiter) ClearBan() {
	l.banMu.Lock()
	defer l.banMu.Unlock()
	l.banUntil = time.Time{}
}

// Acquire blocks until the rate limit allows the next request.
// It also waits if the IP is currently banned.
// Returns an error only if the context is cancelled.
func (l *Limiter) Acquire(ctx context.Context) error {
	// Wait for ban to expire
	if err := l.waitBan(ctx); err != nil {
		return err
	}

	l.mu.Lock()

	// Double-check ban after acquiring lock
	l.banMu.RLock()
	banned := time.Now().Before(l.banUntil)
	l.banMu.RUnlock()
	if banned {
		l.mu.Unlock()
		if err := l.waitBan(ctx); err != nil {
			return err
		}
		l.mu.Lock()
	}

	wait := l.interval - time.Since(l.lastTime)
	if wait > 0 {
		l.mu.Unlock()
		select {
		case <-time.After(wait):
		case <-ctx.Done():
			return ctx.Err()
		}
		l.mu.Lock()
	}
	l.lastTime = time.Now()
	l.mu.Unlock()
	return nil
}

// SetBan sets a global ban barrier. All requests will block until the ban expires.
func (l *Limiter) SetBan(duration time.Duration) {
	l.banMu.Lock()
	defer l.banMu.Unlock()
	l.banUntil = time.Now().Add(duration)
	slog.Warn("IP banned, all main-site requests paused",
		"duration", duration,
		"until", l.banUntil.Format("15:04:05"))
}

// IsBanned returns true if currently banned.
func (l *Limiter) IsBanned() bool {
	l.banMu.RLock()
	defer l.banMu.RUnlock()
	return time.Now().Before(l.banUntil)
}

func (l *Limiter) waitBan(ctx context.Context) error {
	l.banMu.RLock()
	until := l.banUntil
	prober := l.banProber
	cooldown := l.banCooldown
	l.banMu.RUnlock()

	remaining := time.Until(until)
	if remaining <= 0 {
		return nil
	}

	// Without a prober, fall back to the original behavior: wait the
	// full ban duration, then cooldown.
	if prober == nil {
		slog.Info("waiting for ban to expire", "remaining", remaining.Round(time.Second))
		select {
		case <-time.After(remaining):
		case <-ctx.Done():
			return ctx.Err()
		}
		slog.Info("ban expired, cooling down", "cooldown", cooldown)
		select {
		case <-time.After(cooldown):
		case <-ctx.Done():
			return ctx.Err()
		}
		l.banMu.Lock()
		if !time.Now().Before(l.banUntil) {
			l.banUntil = time.Time{}
		}
		l.banMu.Unlock()
		slog.Info("cooldown complete, resuming requests")
		return nil
	}

	// Exponential backoff probing: wait 30s, 60s, 120s, ... capped at
	// 10min. After each wait, probe to check if the ban is lifted.
	// If the accumulated wait reaches the ban duration, stop probing
	// and fall through to the cooldown.
	const (
		initialBackoff = 30 * time.Second
		maxBackoff     = 10 * time.Minute
		probeTimeout   = 15 * time.Second
	)

	backoff := initialBackoff
	elapsed := time.Duration(0)
	probeNum := 0

	for elapsed < remaining {
		wait := backoff
		if elapsed+wait > remaining {
			wait = remaining - elapsed
		}

		slog.Info("ban backoff waiting before probe",
			"probe", probeNum+1,
			"wait", wait.Round(time.Second),
			"elapsed", elapsed.Round(time.Second),
			"remaining", remaining.Round(time.Second),
		)
		select {
		case <-time.After(wait):
		case <-ctx.Done():
			return ctx.Err()
		}
		elapsed += wait

		probeCtx, cancel := context.WithTimeout(ctx, probeTimeout)
		stillBanned, err := prober(probeCtx)
		cancel()
		probeNum++

		if err != nil {
			slog.Warn("ban probe inconclusive, continuing backoff",
				"probe", probeNum, "error", err)
		} else if !stillBanned {
			slog.Info("ban probe recovered, clearing ban",
				"probe", probeNum, "elapsed", elapsed.Round(time.Second))
			l.banMu.Lock()
			l.banUntil = time.Time{}
			l.banMu.Unlock()
			return nil
		} else {
			slog.Info("ban probe still banned",
				"probe", probeNum,
				"elapsed", elapsed.Round(time.Second),
				"next_backoff", backoff.Round(time.Second))
		}

		backoff *= 2
		if backoff > maxBackoff {
			backoff = maxBackoff
		}
	}

	// Ban duration exhausted without recovery signal — cooldown before
	// resuming normal requests.
	slog.Info("ban duration exhausted, cooling down", "cooldown", cooldown)
	select {
	case <-time.After(cooldown):
	case <-ctx.Done():
		return ctx.Err()
	}
	l.banMu.Lock()
	if !time.Now().Before(l.banUntil) {
		l.banUntil = time.Time{}
	}
	l.banMu.Unlock()
	slog.Info("cooldown complete, resuming requests")
	return nil
}

// SimpleLimiter is a rate limiter without ban awareness (for CDN/thumb requests).
type SimpleLimiter struct {
	mu       sync.Mutex
	interval time.Duration
	lastTime time.Time
}

func NewSimple(interval time.Duration) *SimpleLimiter {
	return &SimpleLimiter{interval: interval}
}

func (l *SimpleLimiter) Acquire(ctx context.Context) error {
	l.mu.Lock()

	wait := l.interval - time.Since(l.lastTime)
	if wait > 0 {
		l.mu.Unlock()
		select {
		case <-time.After(wait):
		case <-ctx.Done():
			return ctx.Err()
		}
		l.mu.Lock()
	}
	l.lastTime = time.Now()
	l.mu.Unlock()
	return nil
}
