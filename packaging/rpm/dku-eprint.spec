Name:           dku-eprint
Version:        1.0.0
Release:        1%{?dist}
Summary:        Linux CUPS driver for the DKU ePrint (Pharos Uniprint) service

License:        MIT
URL:            https://github.com/pomegranar/dku-eprint-linux
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch

Requires:       cups
Requires:       python3
Recommends:     zenity

%description
A CUPS backend and helper tools that let a Linux machine print to Duke
Kunshan University's ePrint service, which runs Pharos Uniprint. Jobs are
held at the server and released with a DKUCard at any ePrint station.

Includes an optional per-user agent that asks for the NetID in a desktop
dialog for each job, mirroring the macOS client's behaviour.

The PPD files under %{_datadir}/ppd/dku-eprint are unmodified vendor files
from Ricoh and Lexmark and are not covered by this package's MIT license;
see THIRD-PARTY.md.

%prep
%autosetup

%install
install -d -m 755 %{buildroot}%{_datadir}/%{name}
install -m 644 src/eprint_pharos.py %{buildroot}%{_datadir}/%{name}/
install -m 644 src/eprint_config.py %{buildroot}%{_datadir}/%{name}/

# The vendor Ricoh PPDs name a macOS-only filter; cupsd stops every job to a
# queue whose PPD references a filter it cannot execute.
tools/prepare-ppds.sh vendor/ppd %{buildroot}%{_datadir}/ppd/%{name}

install -d -m 755 %{buildroot}%{_prefix}/lib/cups/backend
install -m 700 src/popup %{buildroot}%{_prefix}/lib/cups/backend/popup

install -d -m 755 %{buildroot}%{_bindir}
install -m 755 src/dku-eprint       %{buildroot}%{_bindir}/dku-eprint
install -m 755 src/dku-eprint-agent %{buildroot}%{_bindir}/dku-eprint-agent

install -d -m 755 %{buildroot}%{_userunitdir}
install -m 644 packaging/systemd/dku-eprint-agent.service %{buildroot}%{_userunitdir}/

install -d -m 755 %{buildroot}%{_sysconfdir}/%{name}
install -m 644 packaging/eprint.conf %{buildroot}%{_sysconfdir}/%{name}/eprint.conf

%post
if [ $1 -eq 1 ]; then
    # Enable the NetID dialog agent for every user's future session.
    systemctl --global enable dku-eprint-agent.service >/dev/null 2>&1 || :
    # ...and for anyone already logged in, so printing works without a re-login.
    for _uid in $(loginctl list-users --no-legend 2>/dev/null | awk '{print $1}'); do
        systemctl --user -M "${_uid}@" start dku-eprint-agent.service \
            >/dev/null 2>&1 || :
    done

    # Queues need cupsd. Start it if it is not already up; if that fails, say so
    # rather than failing the package install.
    if ! systemctl is-active --quiet cups 2>/dev/null; then
        systemctl start cups >/dev/null 2>&1 || :
    fi
    if %{_bindir}/dku-eprint add-queues >/dev/null 2>&1; then
        echo "DKU ePrint queues are ready. Print to ePrint-Ricoh-BW and enter"
        echo "your NetID when prompted; release at any ePrint station."
    else
        echo "DKU ePrint installed, but the print queues could not be created"
        echo "(is cupsd running?). Finish with: sudo dku-eprint add-queues"
    fi
fi

%preun
if [ $1 -eq 0 ]; then
    %{_bindir}/dku-eprint remove-queues >/dev/null 2>&1 || :
    systemctl --global disable dku-eprint-agent.service >/dev/null 2>&1 || :
fi

%files
%license LICENSE
%doc README.md THIRD-PARTY.md docs/PROTOCOL.md
%dir %{_datadir}/%{name}
%{_datadir}/%{name}/*.py
%dir %{_datadir}/ppd/%{name}
%{_datadir}/ppd/%{name}/*.ppd
%attr(700,root,root) %{_prefix}/lib/cups/backend/popup
%{_bindir}/dku-eprint
%{_bindir}/dku-eprint-agent
%{_userunitdir}/dku-eprint-agent.service
%dir %{_sysconfdir}/%{name}
%config(noreplace) %{_sysconfdir}/%{name}/eprint.conf

%changelog
* Sat Sep 19 2026 Anar Nyambayar <an301@duke.edu> - 1.0.0-1
- Initial package
