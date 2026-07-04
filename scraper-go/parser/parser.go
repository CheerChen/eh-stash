package parser

import (
	"regexp"
	"strconv"
	"strings"

	"github.com/PuerkitoBio/goquery"
)

var (
	gidTokenRE     = regexp.MustCompile(`/g/(\d+)/([a-f0-9]+)/`)
	nextCursorRE   = regexp.MustCompile(`[?&]next=([^&"\s]+)`)
	ratingRE       = regexp.MustCompile(`([0-5](?:\.\d+)?)`)
	totalCountRE   = regexp.MustCompile(`Found\s+(?:about\s+)?([\d,]+)\s+results`)
	tagClassRE     = regexp.MustCompile(`^gt`)
	bgPosRE        = regexp.MustCompile(`background-position\s*:\s*(-?\d+)px\s+(-?\d+)px`)
	spaceRE        = regexp.MustCompile(`\s+`)
	thumbURLRE     = regexp.MustCompile(`url\((.+?)\)`)
	postedIDRE     = regexp.MustCompile(`^posted_`)
	digitRE        = regexp.MustCompile(`(\d+)`)
	ratingCountRE  = regexp.MustCompile(`(\d[\d,]*)`)
	torrentCountRE = regexp.MustCompile(`Torrent Download\s*\((\d+)\)`)
	archiverURLRE  = regexp.MustCompile(`popUp\(\s*'(https?://[^']+archiver[^']+)'`)
	fileSizeRE     = regexp.MustCompile(`(?i)([\d.]+)\s*([KMGT]?i?B)`)
	gidInPathRE    = regexp.MustCompile(`/g/(\d+)/`)
)

type GalleryListItem struct {
	GID         int64
	Token       string
	Title       string
	RatingSig   string
	RatingEst   *float64
	VisibleTags []string
	FavoritedAt *string
	IsDeleted   bool
}

type ListResult struct {
	Items      []GalleryListItem
	NextCursor *string
	TotalCount *int
}

type GalleryDetail struct {
	Title        string
	TitleJPN     string
	Category     string
	Uploader     string
	UploaderURL  string
	Rating       *float64
	RatingCount  *int
	Thumb        string
	Posted       string
	Language     string
	Pages        int
	FavCount     int
	CommentCount int
	Tags         map[string][]string

	// Fields previously discarded — captured since 006_detail_extras.
	FileSize      string  // raw "3.54 GiB"
	FileSizeBytes *int64  // parsed numeric bytes
	Visible       string  // "Yes" | "No (Replaced)" | ...
	ParentGID     *int64  // gid extracted from Parent: link
	TorrentCount  int     // "Torrent Download (N)"
	IsExpunged    bool    // visible contains "Replaced" or expunged banner
	Comments      []Comment
}

// Comment is a single user comment from the gallery detail page.
type Comment struct {
	Index             int    // 0-based position on the page
	Author            string
	AuthorURL         string
	PostedAt          string // raw "26 June 2026, 15:56"
	Score             *int   // vote tally, nil when hidden
	Body              string
	IsUploaderComment bool
}

func normalizeText(s string) string {
	return strings.TrimSpace(spaceRE.ReplaceAllString(s, " "))
}

func extractRatingSignal(sel *goquery.Selection) (string, *float64) {
	// Try CSS sprite-based rating
	sel.Find(".ir").Each(func(_ int, ir *goquery.Selection) {
		// Already found? skip via closure
	})

	var sig string
	var est *float64

	sel.Find("[class*='ir']").EachWithBreak(func(_ int, ir *goquery.Selection) bool {
		style, _ := ir.Attr("style")
		style = normalizeText(style)
		m := bgPosRE.FindStringSubmatch(style)
		if m == nil {
			title, _ := ir.Attr("title")
			title = normalizeText(title)
			if title == "" {
				return true // continue
			}
			mt := ratingRE.FindStringSubmatch(title)
			if mt != nil {
				v, _ := strconv.ParseFloat(mt[1], 64)
				sig = "title:" + mt[1]
				est = &v
				return false // break
			}
			return true
		}
		x, _ := strconv.Atoi(m[1])
		y, _ := strconv.Atoi(m[2])
		if y == -1 {
			v := 5.0 - float64(abs(x))/16.0
			v = clamp(v, 0, 5)
			sig = "sprite:x=" + m[1] + ",y=" + m[2]
			est = &v
			return false
		}
		if y == -21 {
			v := 4.5 - float64(abs(x))/16.0
			v = clamp(v, 0, 5)
			sig = "sprite:x=" + m[1] + ",y=" + m[2]
			est = &v
			return false
		}
		return true
	})

	if est != nil {
		return sig, est
	}

	// Fallback: text-based rating
	for _, class := range []string{".gl4e", ".gl4t", ".gl5t", ".gl5m", ".gl5c"} {
		node := sel.Find(class)
		if node.Length() == 0 {
			continue
		}
		text := normalizeText(node.Text())
		m := ratingRE.FindStringSubmatch(text)
		if m != nil {
			v, _ := strconv.ParseFloat(m[1], 64)
			sig = "text:" + m[1]
			est = &v
			return sig, est
		}
	}
	return "", nil
}

func extractVisibleTags(sel *goquery.Selection) []string {
	tags := make(map[string]struct{})

	sel.Find("*").Each(func(_ int, node *goquery.Selection) {
		classes, _ := node.Attr("class")
		if classes == "" {
			return
		}
		for _, c := range strings.Fields(classes) {
			if tagClassRE.MatchString(c) {
				text := strings.ToLower(normalizeText(node.Text()))
				if text != "" && len(text) <= 80 {
					tags[text] = struct{}{}
				}
				return
			}
		}
	})

	if len(tags) > 0 {
		return mapKeys(tags)
	}

	// Fallback: f_search links
	sel.Find("a[href]").Each(func(_ int, a *goquery.Selection) {
		href, _ := a.Attr("href")
		if !strings.Contains(href, "f_search=") {
			return
		}
		text := strings.ToLower(normalizeText(a.Text()))
		if text == "" || len(text) > 80 {
			return
		}
		if text == "archive download" || text == "torrent download" {
			return
		}
		tags[text] = struct{}{}
	})
	return mapKeys(tags)
}

func ParseGalleryList(html string) (*ListResult, error) {
	doc, err := goquery.NewDocumentFromReader(strings.NewReader(html))
	if err != nil {
		return nil, err
	}

	result := &ListResult{}

	// Total count
	if m := totalCountRE.FindStringSubmatch(html); m != nil {
		n, _ := strconv.Atoi(strings.ReplaceAll(m[1], ",", ""))
		result.TotalCount = &n
	}

	itg := doc.Find(".itg")
	if itg.Length() == 0 {
		return result, nil
	}

	// In extended mode (.itg is a <table>), iterate over <tr> rows.
	// In other modes (.itg is a <div>), iterate over direct children.
	var rows *goquery.Selection
	if goquery.NodeName(itg) == "table" {
		rows = itg.Find("tr")
	} else {
		rows = itg.Children()
	}

	rows.Each(func(_ int, el *goquery.Selection) {
		glname := el.Find(".glname")
		if glname.Length() == 0 {
			return
		}

		// Find <a> link
		a := glname.Find("a").First()
		if a.Length() == 0 {
			// Check parent
			parent := glname.Parent()
			if goquery.NodeName(parent) == "a" {
				a = parent
			}
		}
		if a.Length() == 0 {
			return
		}

		href, _ := a.Attr("href")
		m := gidTokenRE.FindStringSubmatch(href)
		if m == nil {
			return
		}
		gid, _ := strconv.ParseInt(m[1], 10, 64)
		token := m[2]

		// Title: deepest child text
		title := extractDeepestText(glname)
		ratingSig, ratingEst := extractRatingSignal(el)
		visibleTags := extractVisibleTags(el)

		// Favorited at
		var favAt *string
		el.Find("p").EachWithBreak(func(_ int, p *goquery.Selection) bool {
			if strings.TrimSpace(p.Text()) == "Favorited:" {
				next := p.Next()
				if next.Length() > 0 {
					text := strings.TrimSpace(next.Text())
					if text != "" {
						favAt = &text
					}
				}
				return false
			}
			return true
		})

		// Deleted detection
		isDeleted := false
		el.Find("[id]").Each(func(_ int, node *goquery.Selection) {
			id, _ := node.Attr("id")
			if postedIDRE.MatchString(id) && node.Find("s").Length() > 0 {
				isDeleted = true
			}
		})

		result.Items = append(result.Items, GalleryListItem{
			GID:         gid,
			Token:       token,
			Title:       title,
			RatingSig:   ratingSig,
			RatingEst:   ratingEst,
			VisibleTags: visibleTags,
			FavoritedAt: favAt,
			IsDeleted:   isDeleted,
		})
	})

	// Next cursor
	dnext := doc.Find("#dnext")
	if dnext.Length() > 0 {
		href, _ := dnext.Attr("href")
		m := nextCursorRE.FindStringSubmatch(href)
		if m != nil {
			result.NextCursor = &m[1]
		}
	}

	return result, nil
}

func ParseDetail(html string) (*GalleryDetail, error) {
	doc, err := goquery.NewDocumentFromReader(strings.NewReader(html))
	if err != nil {
		return nil, err
	}

	gm := doc.Find(".gm")
	if gm.Length() == 0 {
		return nil, nil
	}

	d := &GalleryDetail{}

	d.Title = strings.TrimSpace(gm.Find("#gn").Text())
	d.TitleJPN = strings.TrimSpace(gm.Find("#gj").Text())

	// Category
	ce := gm.Find(".cn")
	if ce.Length() == 0 {
		ce = gm.Find(".cs")
	}
	d.Category = strings.TrimSpace(ce.Text())

	// Uploader (+ profile link)
	d.Uploader = strings.TrimSpace(gm.Find("#gdn").Text())
	if gdn := gm.Find("#gdn"); gdn.Length() > 0 {
		if a := gdn.Find("a"); a.Length() > 0 {
			if href, ok := a.Attr("href"); ok {
				d.UploaderURL = href
			}
		}
	}

	// Rating
	ratingLabel := gm.Find("#rating_label")
	if ratingLabel.Length() > 0 {
		rtext := strings.TrimSpace(ratingLabel.Text())
		if !strings.Contains(rtext, "Not Yet Rated") {
			idx := strings.Index(rtext, " ")
			if idx != -1 {
				if v, err := strconv.ParseFloat(rtext[idx+1:], 64); err == nil {
					d.Rating = &v
				}
			}
		}
	}

	// Rating count (#rating_count span)
	if rc := doc.Find("#rating_count"); rc.Length() > 0 {
		rctext := strings.TrimSpace(rc.Text())
		if m := ratingCountRE.FindStringSubmatch(rctext); m != nil {
			n, _ := strconv.Atoi(strings.ReplaceAll(m[1], ",", ""))
			d.RatingCount = &n
		}
	}

	// Thumb URL
	gd1 := gm.Find("#gd1 div")
	if gd1.Length() > 0 {
		style, _ := gd1.Attr("style")
		if m := thumbURLRE.FindStringSubmatch(style); m != nil {
			d.Thumb = strings.Trim(m[1], "'\"")
		}
	}

	// Detail table #gdd
	gm.Find("#gdd tr").Each(func(_ int, tr *goquery.Selection) {
		tds := tr.Find("td")
		if tds.Length() < 2 {
			return
		}
		key := strings.TrimSpace(tds.First().Text())
		value := strings.TrimSpace(tds.Last().Text())

		switch {
		case strings.HasPrefix(key, "Posted"):
			d.Posted = value
		case strings.HasPrefix(key, "Parent"):
			if a := tds.Last().Find("a"); a.Length() > 0 {
				if href, ok := a.Attr("href"); ok {
					if m := gidInPathRE.FindStringSubmatch(href); m != nil {
						gid, _ := strconv.ParseInt(m[1], 10, 64)
						d.ParentGID = &gid
					}
				}
			}
		case strings.HasPrefix(key, "Visible"):
			d.Visible = value
		case strings.HasPrefix(key, "Language"):
			d.Language = value
		case strings.HasPrefix(key, "File Size"):
			d.FileSize = value
			d.FileSizeBytes = parseFileSizeBytes(value)
		case strings.HasPrefix(key, "Length"):
			idx := strings.Index(value, " ")
			if idx >= 0 {
				if n, err := strconv.Atoi(strings.ReplaceAll(value[:idx], ",", "")); err == nil {
					d.Pages = n
				}
			}
		case strings.HasPrefix(key, "Favorited"):
			switch {
			case value == "Never":
				d.FavCount = 0
			case value == "Once":
				d.FavCount = 1
			default:
				idx := strings.Index(value, " ")
				if idx >= 0 {
					if n, err := strconv.Atoi(strings.ReplaceAll(value[:idx], ",", "")); err == nil {
						d.FavCount = n
					}
				}
			}
		}
	})

	// Comment count + actual comment content
	cdiv := doc.Find("#cdiv")
	if cdiv.Length() > 0 {
		aall := cdiv.Find("#aall")
		if aall.Length() > 0 {
			if m := digitRE.FindStringSubmatch(aall.Text()); m != nil {
				d.CommentCount, _ = strconv.Atoi(m[1])
			} else {
				d.CommentCount = cdiv.Find(".c1").Length()
			}
		} else {
			d.CommentCount = cdiv.Find(".c1").Length()
		}

		// Capture comment bodies. .c1 is each comment block; inside:
		//   .c3 = "Posted on <date> by: <author link>"
		//   .c4 = label (e.g. "Uploader Comment")
		//   .c6 = comment body
		//   .c7 = vote tally (often empty/hidden)
		cdiv.Find(".c1").Each(func(idx int, c1 *goquery.Selection) {
			c := Comment{Index: idx}

			if c3 := c1.Find(".c3"); c3.Length() > 0 {
				c3text := normalizeText(c3.Text())
				// "Posted on 26 June 2026, 15:56 by: 114514beastman"
				if a := c3.Find("a"); a.Length() > 0 {
					c.Author = strings.TrimSpace(a.Text())
					if href, ok := a.Attr("href"); ok {
						c.AuthorURL = href
					}
				}
				if i := strings.Index(c3text, "Posted on "); i >= 0 {
					rest := c3text[i+len("Posted on "):]
					if j := strings.Index(rest, " by:"); j >= 0 {
						c.PostedAt = strings.TrimSpace(rest[:j])
					}
				}
			}

			if c4 := c1.Find(".c4"); c4.Length() > 0 {
				if strings.Contains(normalizeText(c4.Text()), "Uploader Comment") {
					c.IsUploaderComment = true
				}
			}

			if c6 := c1.Find(".c6"); c6.Length() > 0 {
				c.Body = normalizeText(c6.Text())
			}

			if c7 := c1.Find(".c7"); c7.Length() > 0 {
				c7text := normalizeText(c7.Text())
				if c7text != "" {
					if m := digitRE.FindStringSubmatch(c7text); m != nil {
						n, _ := strconv.Atoi(m[1])
						c.Score = &n
					}
				}
			}

			d.Comments = append(d.Comments, c)
		})
	}

	// Tags
	taglist := doc.Find("#taglist")
	if taglist.Length() > 0 {
		d.Tags = make(map[string][]string)
		taglist.Find("tr").Each(func(_ int, tr *goquery.Selection) {
			tds := tr.Find("td")
			if tds.Length() < 2 {
				return
			}
			ns := strings.TrimRight(strings.TrimSpace(tds.First().Text()), ":")
			if ns == "" {
				ns = "misc"
			}
			var tagValues []string
			tds.Last().Find("div a").Each(func(_ int, a *goquery.Selection) {
				t := strings.TrimSpace(a.Text())
				if t != "" {
					tagValues = append(tagValues, t)
				}
			})
			if len(tagValues) > 0 {
				d.Tags[ns] = tagValues
			}
		})
	}

	// Torrent count from #gd5 "Torrent Download (N)"
	if gd5 := doc.Find("#gd5"); gd5.Length() > 0 {
		gd5HTML, _ := gd5.Html()
		if m := torrentCountRE.FindStringSubmatch(gd5HTML); m != nil {
			d.TorrentCount, _ = strconv.Atoi(m[1])
		}
	}

	// IsExpunged: visible field contains "Replaced", or the page shows an
	// expunged banner. The visible flag is the reliable signal; the banner
	// check is a fallback for pages where #gdd wasn't parsed.
	if strings.Contains(strings.ToLower(d.Visible), "replaced") {
		d.IsExpunged = true
	}
	if !d.IsExpunged {
		if doc.Find(".gp").Length() > 0 {
			pageText := strings.ToLower(doc.Text())
			if strings.Contains(pageText, "has been removed") ||
				strings.Contains(pageText, "is expunged") {
				d.IsExpunged = true
			}
		}
	}

	return d, nil
}

func extractDeepestText(sel *goquery.Selection) string {
	node := sel
	for {
		children := node.Children()
		if children.Length() == 0 {
			break
		}
		node = children.First()
	}
	return normalizeText(node.Text())
}

func abs(x int) int {
	if x < 0 {
		return -x
	}
	return x
}

func clamp(v, lo, hi float64) float64 {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}

func mapKeys(m map[string]struct{}) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	return keys
}

// parseFileSizeBytes converts a raw file size string like "3.54 GiB" or
// "18.39 MiB" into a byte count. Returns nil when the string doesn't match.
func parseFileSizeBytes(s string) *int64 {
	m := fileSizeRE.FindStringSubmatch(s)
	if m == nil {
		return nil
	}
	val, err := strconv.ParseFloat(m[1], 64)
	if err != nil {
		return nil
	}
	unit := strings.ToLower(m[2])
	var bytes float64
	switch unit {
	case "b":
		bytes = val
	case "kib", "kb":
		bytes = val * 1024
	case "mib", "mb":
		bytes = val * 1024 * 1024
	case "gib", "gb":
		bytes = val * 1024 * 1024 * 1024
	case "tib", "tb":
		bytes = val * 1024 * 1024 * 1024 * 1024
	default:
		return nil
	}
	n := int64(bytes)
	return &n
}
