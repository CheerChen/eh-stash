package egress

import (
	"context"
	"errors"
	"log/slog"
	"sync"
	"time"
)

type Mode string

const (
	ModeProxy  Mode = "proxy"
	ModeDirect Mode = "direct"
)

type State string

const (
	StateProxyPrimary State = "proxy_primary"
	StateDirectProbe  State = "direct_probe"
)

type ErrKind string

const (
	ErrKindNone         ErrKind = ""
	ErrKindBan          ErrKind = "ban"
	ErrKindAuth         ErrKind = "auth"
	ErrKindProxyConnect ErrKind = "proxy_connect"
	ErrKindTLSHandshake ErrKind = "tls_handshake"
	ErrKindTimeout      ErrKind = "timeout"
	ErrKindHTTPStatus   ErrKind = "http_status"
	ErrKindParse        ErrKind = "parse"
)

type ProbeFunc func(ctx context.Context, mode Mode) error

type Config struct {
	ProxyURL              string
	ProxyFailThreshold    int
	ProxyRecoverThreshold int
	ProbeInterval         time.Duration
	MinSwitchInterval     time.Duration
	ProbeTimeout          time.Duration
}

type Snapshot struct {
	Mode                 Mode
	State                State
	LastSwitchAt         time.Time
	LastSwitchReason     string
	ConsecutiveProxyFail int
	ConsecutiveProxyOK   int
	LastProbeAt          time.Time
	LastProbeError       string
}

type Manager struct {
	cfg Config

	mu        sync.RWMutex
	mode      Mode
	state     State
	prober    ProbeFunc
	lastProbe time.Time

	lastSwitchAt         time.Time
	lastSwitchReason     string
	consecutiveProxyFail int
	consecutiveProxyOK   int
	lastProbeError       string
}

func New(cfg Config) *Manager {
	if cfg.ProxyFailThreshold <= 0 {
		cfg.ProxyFailThreshold = 3
	}
	if cfg.ProxyRecoverThreshold <= 0 {
		cfg.ProxyRecoverThreshold = 2
	}
	if cfg.ProbeInterval <= 0 {
		cfg.ProbeInterval = 30 * time.Second
	}
	if cfg.MinSwitchInterval <= 0 {
		cfg.MinSwitchInterval = 2 * time.Minute
	}
	if cfg.ProbeTimeout <= 0 {
		cfg.ProbeTimeout = 10 * time.Second
	}

	mode := ModeDirect
	state := StateDirectProbe
	if cfg.ProxyURL != "" {
		mode = ModeProxy
		state = StateProxyPrimary
	}

	return &Manager{
		cfg:   cfg,
		mode:  mode,
		state: state,
	}
}

func (m *Manager) SetProber(prober ProbeFunc) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.prober = prober
}

func (m *Manager) CurrentMode() Mode {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.mode
}

func (m *Manager) CurrentProxyURL() string {
	m.mu.RLock()
	defer m.mu.RUnlock()
	if m.mode == ModeProxy {
		return m.cfg.ProxyURL
	}
	return ""
}

func (m *Manager) Snapshot() Snapshot {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return Snapshot{
		Mode:                 m.mode,
		State:                m.state,
		LastSwitchAt:         m.lastSwitchAt,
		LastSwitchReason:     m.lastSwitchReason,
		ConsecutiveProxyFail: m.consecutiveProxyFail,
		ConsecutiveProxyOK:   m.consecutiveProxyOK,
		LastProbeAt:          m.lastProbe,
		LastProbeError:       m.lastProbeError,
	}
}

func (m *Manager) ReportSuccess(mode Mode) {
	if mode != ModeProxy {
		return
	}

	m.mu.Lock()
	defer m.mu.Unlock()
	m.consecutiveProxyFail = 0
	if m.state == StateDirectProbe {
		return
	}
	m.consecutiveProxyOK++
}

func (m *Manager) ReportFailure(mode Mode, kind ErrKind, err error) {
	if mode != ModeProxy || !isProxyPathFailure(kind) {
		return
	}

	m.mu.Lock()
	defer m.mu.Unlock()
	m.consecutiveProxyFail++
	m.consecutiveProxyOK = 0
	if m.consecutiveProxyFail < m.cfg.ProxyFailThreshold {
		return
	}
	if !m.canSwitchLocked() {
		return
	}
	m.switchLocked(ModeDirect, StateDirectProbe, "proxy degraded: "+kindString(kind, err))
}

func (m *Manager) Reconcile(ctx context.Context) {
	m.mu.RLock()
	mode := m.mode
	state := m.state
	prober := m.prober
	shouldProbe := mode == ModeDirect && state == StateDirectProbe && prober != nil && time.Since(m.lastProbe) >= m.cfg.ProbeInterval
	timeout := m.cfg.ProbeTimeout
	m.mu.RUnlock()

	if !shouldProbe {
		return
	}

	probeCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	err := prober(probeCtx, ModeProxy)

	m.mu.Lock()
	defer m.mu.Unlock()
	m.lastProbe = time.Now()
	if err != nil {
		m.consecutiveProxyOK = 0
		m.lastProbeError = err.Error()
		slog.Warn("[EGRESS] proxy probe failed", "error", err)
		return
	}

	m.lastProbeError = ""
	m.consecutiveProxyOK++
	slog.Info("[EGRESS] proxy probe succeeded", "streak", m.consecutiveProxyOK)
	if m.consecutiveProxyOK < m.cfg.ProxyRecoverThreshold {
		return
	}
	if !m.canSwitchLocked() {
		return
	}
	m.switchLocked(ModeProxy, StateProxyPrimary, "proxy recovered")
}

func (m *Manager) canSwitchLocked() bool {
	if m.lastSwitchAt.IsZero() {
		return true
	}
	return time.Since(m.lastSwitchAt) >= m.cfg.MinSwitchInterval
}

func (m *Manager) switchLocked(mode Mode, state State, reason string) {
	if m.mode == mode && m.state == state {
		return
	}
	prevMode := m.mode
	prevState := m.state
	m.mode = mode
	m.state = state
	m.lastSwitchAt = time.Now()
	m.lastSwitchReason = reason
	m.consecutiveProxyFail = 0
	m.consecutiveProxyOK = 0
	slog.Warn("[EGRESS] mode changed",
		"from_mode", prevMode,
		"from_state", prevState,
		"to_mode", mode,
		"to_state", state,
		"reason", reason,
	)
}

func isProxyPathFailure(kind ErrKind) bool {
	return kind == ErrKindProxyConnect || kind == ErrKindTLSHandshake || kind == ErrKindTimeout
}

func kindString(kind ErrKind, err error) string {
	if kind == ErrKindNone {
		if err != nil {
			return err.Error()
		}
		return "unknown"
	}
	if err == nil {
		return string(kind)
	}
	return string(kind) + ": " + err.Error()
}

func ClassifyProbeError(err error) ErrKind {
	if err == nil {
		return ErrKindNone
	}
	if errors.Is(err, context.DeadlineExceeded) || errors.Is(err, context.Canceled) {
		return ErrKindTimeout
	}
	return ErrKindTLSHandshake
}
