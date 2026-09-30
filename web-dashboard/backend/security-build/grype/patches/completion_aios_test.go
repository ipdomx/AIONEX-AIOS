package commands

// AIONEX regression: preserve Docker-backed completion using the supported
// modular client. This server is synthetic loopback only, never a Docker daemon.
import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strings"
	"sync/atomic"
	"testing"

	"github.com/spf13/cobra"
)

func TestAIOSModularDockerCompletion(t *testing.T) {
	for _, tc := range []struct {
		name, prefix, body, api string
		status                  int
		want                    []string
		wantErr                 bool
	}{
		{"prefix", "aios/", `[{"RepoTags":["aios/one:1","other:1","aios/one:2"]},{"RepoTags":["aios/two:1"]}]`, "1.56", 200, []string{"aios/one:1", "aios/one:2", "aios/two:1"}, false},
		{"all-tags", "", `[{"RepoTags":["one:1","two:2"]}]`, "1.56", 200, []string{"one:1", "two:2"}, false},
		{"empty", "missing", `[]`, "1.56", 200, []string{}, false},
		{"negotiate", "one", `[{"RepoTags":["one:1"]}]`, "", 200, []string{"one:1"}, false},
		{"invalid-json", "", `not-json`, "1.56", 200, nil, true},
		{"denied", "", `{"message":"denied"}`, "1.56", 403, nil, true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			var imageCalls atomic.Int32
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.URL.Path == "/_ping" {
					if r.Method != http.MethodHead && r.Method != http.MethodGet {
						t.Errorf("unexpected ping method: %s", r.Method)
					}
					w.Header().Set("API-Version", "1.56")
					w.WriteHeader(200)
					return
				}
				imageCalls.Add(1)
				if r.Method != http.MethodGet || r.URL.Path != "/v1.56/images/json" {
					t.Errorf("unexpected operation: %s %s", r.Method, r.URL.Path)
				}
				if r.URL.Query().Get("all") == "1" {
					t.Error("must not enumerate untagged intermediate images")
				}
				var filters map[string]map[string]bool
				if err := json.Unmarshal([]byte(r.URL.Query().Get("filters")), &filters); err != nil || !reflect.DeepEqual(filters, map[string]map[string]bool{"dangling": {"false": true}}) {
					t.Errorf("dangling filter lost: %v, %v", filters, err)
				}
				w.Header().Set("Content-Type", "application/json")
				w.WriteHeader(tc.status)
				fmt.Fprint(w, tc.body)
			}))
			defer server.Close()
			t.Setenv("DOCKER_HOST", "tcp://"+strings.TrimPrefix(server.URL, "http://"))
			t.Setenv("DOCKER_API_VERSION", tc.api)
			t.Setenv("DOCKER_TLS_VERIFY", "")
			t.Setenv("DOCKER_CERT_PATH", "")
			got, err := listLocalDockerImages(tc.prefix)
			if (err != nil) != tc.wantErr {
				t.Fatalf("error mismatch: %v", err)
			}
			if !tc.wantErr && !reflect.DeepEqual(got, tc.want) {
				t.Fatalf("tags: got %v want %v", got, tc.want)
			}
			if imageCalls.Load() != 1 {
				t.Errorf("expected one image-list request, got %d", imageCalls.Load())
			}
		})
	}
}

func TestAIOSCompletionUnavailablePreservesShellFallback(t *testing.T) {
	t.Setenv("DOCKER_HOST", "unix://"+t.TempDir()+"/absent.sock")
	t.Setenv("DOCKER_API_VERSION", "1.56")
	t.Setenv("DOCKER_TLS_VERIFY", "")
	t.Setenv("DOCKER_CERT_PATH", "")
	items, directive := dockerImageValidArgsFunction(nil, nil, "demo")
	if len(items) != 0 || directive != cobra.ShellCompDirectiveDefault {
		t.Fatalf("shell fallback changed: %v %v", items, directive)
	}
}
