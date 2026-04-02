package worker

import (
	"context"
	"log/slog"
	"time"

	"github.com/CheerChen/eh-stash/scraper-go/db"
)

const (
	grouperIdleInterval = 60 * time.Second
	grouperDebounce     = 30 * time.Second // wait 30s after first trigger, merge all signals
)

// RunGalleryGrouper maintains gallery_group_members.
// Event-driven with debounce: collects triggers for 30s, then runs once.
func RunGalleryGrouper(ctx context.Context, database *db.DB, triggerCh <-chan struct{}) {
	slog.Info("[GROUP] gallery grouper started")

	// Initial run
	empty, err := database.GalleryGroupIsEmpty(ctx)
	if err != nil {
		slog.Error("[GROUP] check empty failed", "error", err)
	} else if empty {
		count, err := database.GalleryGroupFullRebuild(ctx)
		if err != nil {
			slog.Error("[GROUP] full rebuild failed", "error", err)
		} else {
			slog.Info("[GROUP] full rebuild complete", "rows", count)
		}
	} else {
		count, err := database.GalleryGroupIncremental(ctx)
		if err != nil {
			slog.Error("[GROUP] startup incremental failed", "error", err)
		} else if count > 0 {
			slog.Info("[GROUP] startup incremental", "rows", count)
		}
	}

	for {
		// Wait for first trigger
		select {
		case <-triggerCh:
			// got first signal, start debounce window
		case <-time.After(grouperIdleInterval):
			continue
		case <-ctx.Done():
			slog.Info("[GROUP] grouper stopped")
			return
		}

		// Debounce: drain all signals during the window
		timer := time.NewTimer(grouperDebounce)
		merged := 1
	drain:
		for {
			select {
			case <-triggerCh:
				merged++
			case <-timer.C:
				break drain
			case <-ctx.Done():
				timer.Stop()
				return
			}
		}

		slog.Info("[GROUP] running incremental after debounce", "merged_signals", merged)

		count, err := database.GalleryGroupIncremental(ctx)
		if err != nil {
			slog.Error("[GROUP] incremental error", "error", err)
			sleep(ctx, 10*time.Second)
			continue
		}
		if count > 0 {
			slog.Info("[GROUP] incremental", "rows", count)
		}
	}
}
