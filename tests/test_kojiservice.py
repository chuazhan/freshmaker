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
