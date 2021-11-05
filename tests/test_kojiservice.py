# -*- coding: utf-8 -*-
#
# Copyright (c) 2017  Red Hat, Inc.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
from unittest import mock

from freshmaker import kojiservice


@mock.patch("freshmaker.kojiservice.koji")
def test_build_container_csv_mods(mock_koji):
    mock_session = mock.Mock()
    mock_session.buildContainer.return_value = 123
    mock_koji.ClientSession.return_value = mock_session

    svc = kojiservice.KojiService()
    svc.build_container(
        "git@domain.local:namespace/repo.git",
        "1.0",
        "repo-1.0",
        operator_csv_modifications_url="https://domain.local/namespace/repo",
    )

    mock_session.buildContainer.assert_called_once_with(
        "git@domain.local:namespace/repo.git",
        "repo-1.0",
        {
            "git_branch": "1.0",
            "operator_csv_modifications_url": "https://domain.local/namespace/repo",
            "scratch": False,
        },
    )


@mock.patch("freshmaker.kojiservice.koji")
def test_get_ocp_versions_range(mock_koji):
    mock_session = mock.Mock()
    mock_session.getBuild.return_value = {"id": 123}
    archives = [{
        "arch": "x86_64",
        "btype": "image",
        "extra": {
            "docker": {
                "config": {
                    "architecture": "amd64",
                    "config": {
                        "Hostname": "c4b105e29878",
                        "Labels": {
                            "architecture": "x86_64",
                            "com.redhat.component": "foobar-bundle-container",
                            "com.redhat.delivery.backport": "true",
                            "com.redhat.delivery.operator.bundle": "true",
                            "com.redhat.openshift.versions": "v4.5,v4.6"
                        }
                    },
                    "os": "linux"
                },
                "id": "sha256:123"
            },
            "image": {
                "arch": "x86_64"
            }
        },
        "type_name": "tar"
    }]

    mock_session.listArchives.return_value = archives
    mock_koji.ClientSession.return_value = mock_session

    svc = kojiservice.KojiService()
    assert svc.get_ocp_versions_range('foobar-2-123') == "v4.5,v4.6"


@mock.patch("freshmaker.kojiservice.koji")
@mock.patch("freshmaker.kojiservice.requests.get")
@mock.patch("freshmaker.kojiservice.ZipFile")
@mock.patch("freshmaker.kojiservice.BytesIO")
@mock.patch("freshmaker.kojiservice.yaml")
def test_get_bundle_csv_success(
    mock_yaml, mock_bytesio, mock_zipfile, mock_get, mock_koji
):
    mock_session = mock.Mock()
    mock_session.getBuild.return_value = {
        "id": 123,
        "nvr": "foobar-bundle-container-2.0-123",
        "extra": {"operator_manifests_archive": "operator_manifests.zip"}
    }
    mock_koji.ClientSession.return_value = mock_session
    mock_get.return_value = mock.Mock(ok=True)
    mock_zipfile.return_value.namelist.return_value = [
        "foobar-v2.0-opr-1.clusterserviceversion.yaml",
        "foobar_crd.yaml",
        "foobar_artemisaddress_crd.yaml",
        "foobar_artemisscaledown_crd.yaml"
    ]
    mock_yaml.safe_load.return_value = {
        "apiVersion": "operators.coreos.com/v1alpha1",
        "kind": "ClusterServiceVersion",
        "spec": {"version": "2.0-opr-1"},
        "metadata": {"name": "foobar-2.0-opr-1"}
    }

    svc = kojiservice.KojiService()
    csv = svc.get_bundle_csv("foobar-bundle-container-2.0-123")
    assert csv["metadata"]["name"] == "foobar-2.0-opr-1"
    assert csv["spec"]["version"] == "2.0-opr-1"


@mock.patch("freshmaker.kojiservice.log")
@mock.patch("freshmaker.kojiservice.koji")
@mock.patch("freshmaker.kojiservice.requests.get")
def test_get_bundle_csv_unavailable(mock_get, mock_koji, mock_log):
    mock_session = mock.Mock()
    mock_session.getBuild.return_value = {
        "id": 123,
        "nvr": "foobar-bundle-container-2.0-123",
        "extra": {}
    }
    mock_koji.ClientSession.return_value = mock_session

    svc = kojiservice.KojiService()
    csv = svc.get_bundle_csv("foobar-bundle-container-2.0-123")
    assert csv is None
    mock_log.error.assert_any_call(
        "Operator manifests archive is unavaiable for build %s", "foobar-bundle-container-2.0-123"
    )


@mock.patch("freshmaker.kojiservice.koji")
def test_get_modulemd(mock_koji):
    mock_session = mock.Mock()
    build = {'build_id': 1850907,
             'epoch': None,
             'extra': {'typeinfo': {'module': {'modulemd_str': '---\ndocument: modulemd\nversion: 2\ndata:\n  name: ghc\n  stream: "9.2"\n  version: 3620211101111632\n  context: d099bf28\n  summary: Haskell GHC 9.2\n  description: >-\n    This module provides the Glasgow Haskell Compiler version 9.2.1\n  license:\n    module:\n    - MIT\n  xmd:\n    mbs:\n      buildrequires:\n        ghc:\n          context: 5e5ad4a0\n          filtered_rpms: []\n          koji_tag: module-ghc-8.10-3620210920031153-5e5ad4a0\n          ref: 1773e6a0b99813df3a02e83860ca5e51879b79da\n          stream: 8.10\n          version: 3620210920031153\n        platform:\n          context: 00000000\n          filtered_rpms: []\n          koji_tag: module-f36-build\n          ref: f36\n          stream: f36\n          stream_collision_modules: \n          ursine_rpms: \n          version: 1\n      commit: 5405c8a084c04476a956f1b3e49a733b888066a5\n      mse: TRUE\n      rpms:\n        ghc:\n          ref: 9be829cc000e68bb052f15099cac1a0ecac8f4eb\n      scmurl: https://src.fedoraproject.org/modules/ghc.git?#5405c8a084c04476a956f1b3e49a733b888066a5\n      ursine_rpms:\n      - ghc-bytestring-devel-0:0.10.12.0-115.fc35.s390x\n      - ghc-exceptions-prof-0:0.10.4-115.fc35.armv7hl\n  dependencies:\n  - buildrequires:\n      ghc: [8.10]\n      platform: [f36]\n    requires:\n      platform: [f36]\n  references:\n    community: https://www.haskell.org/ghc\n    documentation: https://wiki.haskell.org/GHC\n    tracker: https://gitlab.haskell.org/ghc/ghc/issues\n  profiles:\n    all:\n      description: standard installation\n      rpms:\n      - ghc\n      - ghc-doc\n      - ghc-prof\n    default:\n      description: standard installation\n      rpms:\n      - ghc\n    minimal:\n      description: just compiler and base\n      rpms:\n      - ghc-base-devel\n    small:\n      description: compiler with main core libs\n      rpms:\n      - ghc-devel\n  components:\n    rpms:\n      ghc:\n        rationale: compiler\n        repository: git+https://src.fedoraproject.org/rpms/ghc\n        cache: https://src.fedoraproject.org/repo/pkgs/ghc\n        ref: 9.2\n        buildorder: 1\n        arches: [aarch64, armv7hl, i686, ppc64le, s390x, x86_64]\n...\n',
                                               'name': 'ghc',
                                               'stream': '9.2',
                                               'module_build_service_id': 13274,
                                               'version': '3620211101111632',
                                               'context': 'd099bf28',
                                               'content_koji_tag': 'module-ghc-9.2-3620211101111632-d099bf28'
                                               }
                                    }
                       },
             'id': 1850907,
             'name': 'ghc',
             'nvr': 'ghc-9.2-3620211101111632.d099bf28',
             'package_id': 1853,
             'package_name': 'ghc',
             }

    mock_session.getBuild.return_value = build

    mock_koji.ClientSession.return_value = mock_session

    svc = kojiservice.KojiService()
    mmd = svc.get_modulemd("ghc-9.2-3620211101111632.d099bf28")
    module_name = mmd.get_module_name()
    module_stream = mmd.get_stream_name()
    assert module_name == "ghc"
    assert module_stream == "9.2"
