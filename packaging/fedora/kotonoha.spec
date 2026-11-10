# Native sources ship in the RPM; transaction hooks build against local Qt.
%global debug_package %{nil}

Name:           kotonoha
Version:        0.1.0
Release:        1%{?dist}
Summary:        Desktop lyrics overlay for Linux

License:        MIT AND LGPL-2.1-or-later
URL:            https://github.com/locez/kotonoha
Source0:        %{name}-%{version}.tar.gz
Source1:        qasync-0.28.0-py3-none-any.whl

BuildRequires:  python3-devel
BuildRequires:  python3-scikit-build-core
BuildRequires:  pyproject-rpm-macros
BuildRequires:  gcc-c++
BuildRequires:  cmake
BuildRequires:  qt6-qtbase-devel
BuildRequires:  qt6-qtbase-private-devel
BuildRequires:  qt6-qtwayland-devel
BuildRequires:  layer-shell-qt-devel
BuildRequires:  wayland-devel
BuildRequires:  desktop-file-utils
Requires:       python3
Requires:       python3-pyqt6
Requires:       python3-aiohttp
Requires:       python3-dbus-fast
Requires:       python3-pyyaml
Requires:       layer-shell-qt
Requires:       cmake
Requires:       gcc-c++
Requires:       pkgconf-pkg-config
Requires:       qt6-qtbase-devel
Requires:       qt6-qtbase-private-devel
Requires:       qt6-qtwayland-devel
Requires:       layer-shell-qt-devel
Requires:       wayland-devel
Recommends:     python3-mutagen
Provides:       bundled(python3dist(qasync)) = 0.28.0

%description
Kotonoha displays synchronized lyrics for the currently playing track in a
Wayland layer-shell overlay.

%prep
%autosetup

%build
export SKBUILD_CMAKE_DEFINE=KOTONOHA_BUILD_BRIDGE=OFF
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files kotonoha
install -Dm0755 scripts/rebuild_bridge.py %{buildroot}%{_prefix}/lib/kotonoha/rebuild-bridge
install -Dm0644 CMakeLists.txt %{buildroot}%{_datadir}/kotonoha/native/CMakeLists.txt
install -Dm0644 LICENSE %{buildroot}%{_datadir}/kotonoha/native/LICENSE
install -Dm0644 src/kotonoha/layer_shell_bridge.cpp %{buildroot}%{_datadir}/kotonoha/native/src/kotonoha/layer_shell_bridge.cpp
mkdir -p %{buildroot}%{_datadir}/kotonoha/native/src/kotonoha/protocols
cp src/kotonoha/protocols/*.xml %{buildroot}%{_datadir}/kotonoha/native/src/kotonoha/protocols/
mkdir -p %{buildroot}/var/lib/kotonoha
ln -s /var/lib/kotonoha/libkoto-layer.so %{buildroot}%{python3_sitearch}/kotonoha/libkoto-layer.so
python3 -m zipfile -e %{SOURCE1} %{buildroot}%{python3_sitelib}
install -Dm0644 packaging/kotonoha.desktop \
    %{buildroot}%{_datadir}/applications/kotonoha.desktop
install -Dm0644 src/kotonoha/assets/icon.png \
    %{buildroot}%{_datadir}/pixmaps/kotonoha.png
install -Dm0644 packaging/dev.locez.kotonoha.metainfo.xml \
    %{buildroot}%{_datadir}/metainfo/dev.locez.kotonoha.metainfo.xml
install -Dm0644 packaging/kotonoha.1 \
    %{buildroot}%{_mandir}/man1/kotonoha.1

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/kotonoha.desktop

%posttrans
if ! %{_prefix}/lib/kotonoha/rebuild-bridge; then
    echo "Kotonoha RPM is installed, but the native bridge rebuild failed; RPM cannot roll back this transaction." >&2
    echo "Fix the build error, then run: sudo /usr/lib/kotonoha/rebuild-bridge" >&2
    exit 1
fi

# Private Qt ABI may change after installation. Run after the whole transaction,
# when both runtime libraries and matching development headers are available.
# RPM indexes file triggers by directory; a partial library filename does not
# match its directory index. Subscribe to real directories, then filter stdin
# so unrelated library transactions do not compile the bridge.
%transfiletriggerin -- %{_libdir} %{_includedir}/qt6
rebuild_needed=0
while IFS= read -r installed_path; do
    case "$installed_path" in
        %{_libdir}/libQt6*.so*|%{_libdir}/libLayerShellQtInterface.so*|%{_includedir}/qt6/*)
            rebuild_needed=1
            ;;
    esac
done
if [ "$rebuild_needed" -eq 1 ] && [ -x %{_prefix}/lib/kotonoha/rebuild-bridge ]; then
    if ! %{_prefix}/lib/kotonoha/rebuild-bridge; then
        echo "Qt update completed, but Kotonoha bridge rebuild failed; retry: sudo /usr/lib/kotonoha/rebuild-bridge" >&2
        exit 1
    fi
fi

%postun
if [ "$1" -eq 0 ]; then
    rm -f /var/lib/kotonoha/libkoto-layer.so /var/lib/kotonoha/build.lock
    if [ -d /var/lib/kotonoha ]; then rmdir /var/lib/kotonoha; fi
fi

%files -f %{pyproject_files}
%{_prefix}/lib/kotonoha/
%{_datadir}/kotonoha/
%{python3_sitearch}/kotonoha/libkoto-layer.so
%dir /var/lib/kotonoha
%ghost /var/lib/kotonoha/libkoto-layer.so
%ghost /var/lib/kotonoha/build.lock
%doc README.md
%license %{python3_sitearch}/share/licenses/kotonoha/LICENSE
%{_bindir}/kotonoha
%{python3_sitelib}/qasync/
%dir %{python3_sitelib}/qasync-0.28.0.dist-info
%{python3_sitelib}/qasync-0.28.0.dist-info/METADATA
%{python3_sitelib}/qasync-0.28.0.dist-info/RECORD
%{python3_sitelib}/qasync-0.28.0.dist-info/WHEEL
%dir %{python3_sitelib}/qasync-0.28.0.dist-info/licenses
%license %{python3_sitelib}/qasync-0.28.0.dist-info/licenses/LICENSE
%{_datadir}/applications/kotonoha.desktop
%{_datadir}/pixmaps/kotonoha.png
%{_datadir}/metainfo/dev.locez.kotonoha.metainfo.xml
%{_mandir}/man1/kotonoha.1*

%changelog
* Sat Jul 11 2026 Locez <locez@locez.com> - 0.1.0-1
- Initial package
