// Kotonoha Wayland layer-shell bridge.
//
// Compiled to libkoto-layer.so and loaded from Python via ctypes (see
// native.py / overlay.py). Promotes a QWindow to a wlr-layer-shell Overlay
// surface so the lyrics float above fullscreen apps, and exposes click-through
// (input region) + positioning control.
//
// IMPORTANT: make_overlay() must run BEFORE the window is shown, otherwise the
// surface already has an xdg-shell role and LayerShellQt refuses to convert it
// ("already has a shell integration"). overlay.py calls activate before show().
//
// Modelled on BiliHUD's bridge: anchor Top|Left and position the fixed-size
// surface with left/top margins (set_anchor_position), which is what makes the
// panel freely draggable.

#include <QWindow>
#include <LayerShellQt/Window>

#include <QMargins>

#include <QGuiApplication>
#include <qpa/qplatformnativeinterface.h>
#include <wayland-client.h>

#include <cstring>  // std::strcmp — used by the layer-shell probe, blur or not

#ifdef KOTONOHA_HAVE_BLUR
#include <cmath>
#include <map>

#include "blur-client-protocol.h"


namespace {
    // KWin blur ("org_kde_kwin_blur") for the frosted-glass surfaces. Bound lazily
    // from the registry; absent on non-KWin compositors, where blur is a no-op.
    struct org_kde_kwin_blur_manager* g_blur_manager = nullptr;
    // One blur object PER surface, so several windows (the overlay pill AND the
    // settings window) can each be frosted independently without clobbering a
    // single shared object.
    std::map<struct wl_surface*, struct org_kde_kwin_blur*> g_blurs;
    bool g_blur_probed = false;

    void registry_global(void*, struct wl_registry* registry, uint32_t name,
                         const char* interface, uint32_t /*version*/) {
        if (std::strcmp(interface, "org_kde_kwin_blur_manager") == 0) {
            g_blur_manager = static_cast<struct org_kde_kwin_blur_manager*>(
                wl_registry_bind(registry, name, &org_kde_kwin_blur_manager_interface, 1));
        }
    }
    void registry_global_remove(void*, struct wl_registry*, uint32_t) {}
    const struct wl_registry_listener kRegistryListener = {registry_global, registry_global_remove};

    struct wl_compositor* get_compositor(QPlatformNativeInterface* native) {
        struct wl_compositor* c = (struct wl_compositor*)native->nativeResourceForIntegration("compositor");
        if (!c) c = (struct wl_compositor*)native->nativeResourceForIntegration("wl_compositor");
        return c;
    }

    // Approximate a rounded rectangle as a wl_region: a full-width middle band
    // plus one 1px strip per corner row inset to the arc. Without this the blur
    // is a sharp rectangle that overhangs the pill's rounded corners.
    void add_rounded_rect(struct wl_region* region, int x, int y, int w, int h, int radius) {
        int r = radius;
        if (r < 0) r = 0;
        if (r * 2 > w) r = w / 2;
        if (r * 2 > h) r = h / 2;
        if (r == 0) {
            wl_region_add(region, x, y, w, h);
            return;
        }
        wl_region_add(region, x, y + r, w, h - 2 * r);  // middle band, full width
        for (int i = 0; i < r; ++i) {
            int dy = r - i;  // vertical distance from the arc centre for this row
            int dx = r - static_cast<int>(std::sqrt(static_cast<double>(r * r - dy * dy)) + 0.5);
            int rw = w - 2 * dx;
            if (rw <= 0) continue;
            wl_region_add(region, x + dx, y + i, rw, 1);            // top row
            wl_region_add(region, x + dx, y + h - 1 - i, rw, 1);   // mirrored bottom row
        }
    }

    struct org_kde_kwin_blur_manager* blur_manager(QPlatformNativeInterface* native) {
        if (g_blur_probed) return g_blur_manager;
        g_blur_probed = true;
        struct wl_display* display = (struct wl_display*)native->nativeResourceForIntegration("wl_display");
        if (!display) display = (struct wl_display*)native->nativeResourceForIntegration("display");
        if (!display) return nullptr;
        struct wl_registry* registry = wl_display_get_registry(display);
        wl_registry_add_listener(registry, &kRegistryListener, nullptr);
        wl_display_roundtrip(display);  // process global advertisements so the bind lands
        return g_blur_manager;
    }
}  // namespace
#endif  // KOTONOHA_HAVE_BLUR


namespace {
    // One-shot probe (always compiled, unlike the blur namespace above): does THIS
    // compositor advertise zwlr_layer_shell_v1? Backs koto_has_layer_shell() so the
    // Python side can pick the top-most-window fallback on ANY layer-shell-less
    // Wayland session (GNOME/Mutter, Weston, Cinnamon) without hard-coding names.
    bool g_layer_shell_present = false;
    bool g_layer_shell_probed = false;

    void ls_registry_global(void* data, struct wl_registry*, uint32_t,
                            const char* interface, uint32_t /*version*/) {
        if (std::strcmp(interface, "zwlr_layer_shell_v1") == 0) {
            *static_cast<bool*>(data) = true;
        }
    }
    void ls_registry_global_remove(void*, struct wl_registry*, uint32_t) {}
    const struct wl_registry_listener kLayerShellRegistryListener = {
        ls_registry_global, ls_registry_global_remove};
}  // namespace


extern "C" {
    // Qt ABI handshake for the ctypes loader (native.py): the version this bridge
    // was built against. The loader refuses a bridge built against a different Qt
    // minor than the running PyQt6 — the bridge links Qt QPA/private API, which
    // carries no cross-minor ABI guarantee.
    const char* koto_layer_qt_version() {
        return QT_VERSION_STR;
    }

    // 1 if the compositor advertises wlr-layer-shell, else 0. Lets the Python side
    // fall back to a top-most ordinary window on a layer-shell-less Wayland session
    // instead of silently no-op'ing every bridge call. Result cached after first.
    int koto_has_layer_shell() {
        if (g_layer_shell_probed) return g_layer_shell_present ? 1 : 0;
        g_layer_shell_probed = true;
        QPlatformNativeInterface* native = QGuiApplication::platformNativeInterface();
        if (!native) return 0;
        struct wl_display* display = (struct wl_display*)native->nativeResourceForIntegration("wl_display");
        if (!display) display = (struct wl_display*)native->nativeResourceForIntegration("display");
        if (!display) return 0;
        struct wl_registry* registry = wl_display_get_registry(display);
        if (!registry) return 0;
        wl_registry_add_listener(registry, &kLayerShellRegistryListener, &g_layer_shell_present);
        wl_display_roundtrip(display);  // process the compositor's global advertisements
        wl_registry_destroy(registry);
        return g_layer_shell_present ? 1 : 0;
    }

    void make_overlay(void* window_ptr) {
        if (!window_ptr) return;

        QWindow* window = static_cast<QWindow*>(window_ptr);
        LayerShellQt::Window* ls_window = LayerShellQt::Window::get(window);

        if (ls_window) {
            ls_window->setLayer(LayerShellQt::Window::LayerOverlay);
            // -1 for no exclusive zone (fully ignored by tiling layout).
            ls_window->setExclusiveZone(-1);
            // Lyrics are passive; no keyboard focus.
            ls_window->setKeyboardInteractivity(LayerShellQt::Window::KeyboardInteractivityNone);
            // Anchor to the top-left corner; the surface keeps its requested size
            // and is positioned by left/top margins (set_anchor_position).
            ls_window->setAnchors(LayerShellQt::Window::Anchors(
                LayerShellQt::Window::AnchorTop | LayerShellQt::Window::AnchorLeft));
            ls_window->setScope("kotonoha");
        }
    }

    // Position the surface via left/top margins (x, y from the top-left anchor).
    void set_anchor_position(void* window_ptr, int x, int y) {
        if (!window_ptr) return;
        QWindow* window = static_cast<QWindow*>(window_ptr);
        LayerShellQt::Window* ls_window = LayerShellQt::Window::get(window);

        if (ls_window) {
            QMargins margins;
            margins.setLeft(x);
            margins.setTop(y);
            margins.setRight(0);
            margins.setBottom(0);
            ls_window->setMargins(margins);
        }
        // Commit the surface right away so the move lands without waiting for the
        // next Qt repaint (reduces the dragging lag / "repainting in place" feel).
        QPlatformNativeInterface* native = QGuiApplication::platformNativeInterface();
        if (native) {
            struct wl_surface* surface = (struct wl_surface*)native->nativeResourceForWindow("surface", window);
            if (surface) {
                wl_surface_commit(surface);
            }
        }
    }

    void set_passthrough(void* window_ptr, bool enabled) {
        if (!window_ptr) return;
        QWindow* window = static_cast<QWindow*>(window_ptr);

        QPlatformNativeInterface* native = QGuiApplication::platformNativeInterface();
        if (!native) return;

        struct wl_surface* surface = (struct wl_surface*)native->nativeResourceForWindow("surface", window);
        if (!surface) return;

        struct wl_compositor* compositor = (struct wl_compositor*)native->nativeResourceForIntegration("compositor");
        if (!compositor) {
            compositor = (struct wl_compositor*)native->nativeResourceForIntegration("wl_compositor");
        }

        if (surface && compositor) {
            if (enabled) {
                // Empty input region -> surface accepts no input (click-through).
                struct wl_region* region = wl_compositor_create_region(compositor);
                wl_surface_set_input_region(surface, region);
                wl_region_destroy(region);
            } else {
                // NULL input region -> infinite region (surface accepts all input).
                wl_surface_set_input_region(surface, nullptr);
            }
            wl_surface_commit(surface);
        }
    }

    // Restrict input to a single rectangle (surface coords). Used while unlocked
    // so only the visible pill catches clicks — the transparent area around it
    // stays click-through instead of the whole big band grabbing every click.
    void set_input_rect(void* window_ptr, int x, int y, int w, int h) {
        if (!window_ptr) return;
        QWindow* window = static_cast<QWindow*>(window_ptr);

        QPlatformNativeInterface* native = QGuiApplication::platformNativeInterface();
        if (!native) return;

        struct wl_surface* surface = (struct wl_surface*)native->nativeResourceForWindow("surface", window);
        if (!surface) return;

        struct wl_compositor* compositor = (struct wl_compositor*)native->nativeResourceForIntegration("compositor");
        if (!compositor) {
            compositor = (struct wl_compositor*)native->nativeResourceForIntegration("wl_compositor");
        }

        if (surface && compositor) {
            struct wl_region* region = wl_compositor_create_region(compositor);
            wl_region_add(region, x, y, w, h);
            wl_surface_set_input_region(surface, region);
            wl_region_destroy(region);
            wl_surface_commit(surface);
        }
    }

    // Ask KWin to blur whatever is behind the pill rectangle (frosted glass).
    // No-op on compositors without the blur protocol; the translucent fill still
    // renders, so the panel just isn't blurred there.
    void set_blur_region(void* window_ptr, int x, int y, int w, int h, int radius) {
#ifndef KOTONOHA_HAVE_BLUR
        (void)window_ptr; (void)x; (void)y; (void)w; (void)h; (void)radius;  // built without blur
#else
        if (!window_ptr) return;
        QWindow* window = static_cast<QWindow*>(window_ptr);
        QPlatformNativeInterface* native = QGuiApplication::platformNativeInterface();
        if (!native) return;
        struct wl_surface* surface = (struct wl_surface*)native->nativeResourceForWindow("surface", window);
        if (!surface) return;
        struct org_kde_kwin_blur_manager* manager = blur_manager(native);
        if (!manager) return;

        // Replace any previous blur for THIS surface (leave other windows' blur).
        auto existing = g_blurs.find(surface);
        if (existing != g_blurs.end()) {
            org_kde_kwin_blur_release(existing->second);
            g_blurs.erase(existing);
        }
        struct org_kde_kwin_blur* blur = org_kde_kwin_blur_manager_create(manager, surface);
        g_blurs[surface] = blur;  // keep it alive so the effect persists
        struct wl_compositor* compositor = get_compositor(native);
        if (compositor) {
            struct wl_region* region = wl_compositor_create_region(compositor);
            add_rounded_rect(region, x, y, w, h, radius);  // match the pill's rounded corners
            org_kde_kwin_blur_set_region(blur, region);
            wl_region_destroy(region);
        }
        org_kde_kwin_blur_commit(blur);
        wl_surface_commit(surface);
#endif  // KOTONOHA_HAVE_BLUR
    }

    void clear_blur(void* window_ptr) {
#ifndef KOTONOHA_HAVE_BLUR
        (void)window_ptr;  // built without the blur protocol
#else
        if (!window_ptr) return;
        QWindow* window = static_cast<QWindow*>(window_ptr);
        QPlatformNativeInterface* native = QGuiApplication::platformNativeInterface();
        if (!native) return;
        struct wl_surface* surface = (struct wl_surface*)native->nativeResourceForWindow("surface", window);
        if (!surface) return;
        struct org_kde_kwin_blur_manager* manager = blur_manager(native);
        if (!manager) return;
        auto existing = g_blurs.find(surface);
        if (existing != g_blurs.end()) {
            org_kde_kwin_blur_release(existing->second);
            g_blurs.erase(existing);
        }
        org_kde_kwin_blur_manager_unset(manager, surface);
        wl_surface_commit(surface);
#endif  // KOTONOHA_HAVE_BLUR
    }

    void set_keyboard_interactivity(void* window_ptr, bool enabled) {
        if (!window_ptr) return;
        QWindow* window = static_cast<QWindow*>(window_ptr);
        LayerShellQt::Window* ls_window = LayerShellQt::Window::get(window);

        if (ls_window) {
            if (enabled) {
                ls_window->setKeyboardInteractivity(LayerShellQt::Window::KeyboardInteractivityOnDemand);
            } else {
                ls_window->setKeyboardInteractivity(LayerShellQt::Window::KeyboardInteractivityNone);
            }
        }
    }
}
