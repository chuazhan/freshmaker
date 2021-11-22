# -*- coding: utf-8 -*-
# Copyright (c) 2021  Red Hat, Inc.
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
# Written by Valerij Maljulin <vmaljuli@redhat.com>
# Written by Chuang Zhang <chuazhan@redhat.com>

import json
import koji
import requests
from kobo import rpmlib
from http import HTTPStatus

from freshmaker import conf, db, log
from freshmaker.errata import Errata
from freshmaker.events import FlatpakModuleAdvisoryReadyEvent
from freshmaker.handlers import ContainerBuildHandler, fail_event_on_handler_exception
from freshmaker.kojiservice import koji_service
from freshmaker.lightblue import LightBlue
from freshmaker.models import Event
from freshmaker.pyxis import Pyxis
from freshmaker.types import (
    ArtifactType, ArtifactBuildState, EventState, RebuildReason)


class RebuildFlatpakApplicationOnModuleReady(ContainerBuildHandler):
    name = 'RebuildFlatpakApplicationOnModuleReady'

    def can_handle(self, event):
        return isinstance(event, FlatpakModuleAdvisoryReadyEvent)

    @fail_event_on_handler_exception
    def handle(self, event):
        """
        TODO: Rebuild images on Errata Advisory.
        """

        if event.dry_run:
            self.force_dry_run()

        self.event = event

        db_event = Event.get_or_create_from_event(db.session, event)
        self.set_context(db_event)

        rebuld_images_list = self._get_rebuild_image_list(event)
        if not rebuld_images_list:
            msg = ("There is no image can be rebuilt. "
                   f"message_id: {event.msg_id}")
            db_event.transition(EventState.SKIPPED, msg)
            db.session.commit()
            self.log_info(msg)
            return []

        lb = LightBlue(server_url=conf.lightblue_server_url,
                       cert=conf.lightblue_certificate,
                       private_key=conf.lightblue_private_key,
                       event_id=self.current_db_event_id)
        images = lb.get_images_by_nvrs(rebuld_images_list)
        builds = self._record_builds(images, event)

        if not builds:
            msg = 'No container images to rebuild for advisory %r' % event.advisory.name
            self.log_info(msg)
            db_event.transition(EventState.SKIPPED, msg)
            db.session.commit()
            return []

    def _get_rebuild_image_list(self, event):
        rebuld_images_list = list()
        flatpak_server_url = "https://flatpaks.engineering.redhat.com"
        self._pyxis = Pyxis(conf.pyxis_server_url)
        errata = Errata()
        errata_id = event.advisory.errata_id

        errata_rpm_nvrs = errata.get_cve_affected_rpm_nvrs(errata_id)
        errata_rpm_dict = self._get_rpm_nvrs_dict(errata_rpm_nvrs)

        with koji_service(conf.koji_profile, log, login=False, dry_run=self.dry_run) as session:
            module_nvrs = errata.get_cve_affected_build_nvrs(errata_id, True)
            for module_nvr in module_nvrs:
                mmd = session.get_modulemd(module_nvr)
                content_index_url = '{}/released/contents/modules/{}:{}.json'.format(flatpak_server_url,
                                                                                     mmd.get_module_name(),
                                                                                     mmd.get_stream_name())
                response = requests.get(content_index_url)
                status_code = response.status_code
                if status_code == HTTPStatus.OK:
                    images_info = response.json().get("Images", [])
                    for image_info in images_info:
                        image_nvr = image_info["ImageNvr"]
                        rebuild_image_id = self._pyxis.get_rebuild_image_id(image_nvr)
                        if rebuild_image_id:
                            image_rpm_nvrs = self._pyxis.get_image_rpm_nvrs(rebuild_image_id)
                            image_rpm_dict = self._get_rpm_nvrs_dict(image_rpm_nvrs)
                            for rpm_name, rpm_nvr_dict in image_rpm_dict.items():
                                errata_nvr_dict = errata_rpm_dict.get(rpm_name)
                                result = rpmlib.compare_nvr(image_rpm_dict, errata_nvr_dict)
                                if result < 0:
                                    rebuld_images_list.append(image_nvr)

        return rebuld_images_list

    def _record_builds(self, images, event):
        """
        Records the images to database.

        :param images list: ContainerImage instances.
        :param event ErrataAdvisoryRPMsSignedEvent: The event this handler
            is currently handling.
        :return: a mapping between docker image build NVR and
            corresponding ArtifactBuild object representing a future rebuild of
            that docker image. It is extended by including those docker images
            stored into database.
        :rtype: dict
        """
        db_event = Event.get_or_create_from_event(db.session, event)

        # Used as tmp dict with {brew_build_nvr: ArtifactBuild, ...} mapping.
        builds = {}
        for image in images:
            self.set_context(db_event)

            nvr = image.nvr
            if nvr in builds:
                self.log_debug("Skipping recording build %s, "
                               "it is already in db", nvr)
                continue

            parent_build = db_event.get_artifact_build_from_event_dependencies(nvr)
            if parent_build:
                self.log_debug(
                    "Skipping recording build %s, "
                    "it is already built in dependant event %r", nvr, parent_build[0].event_id)
                continue

            self.log_debug("Recording %s", nvr)
            parent_nvr = image["parent"].nvr \
                if "parent" in image and image["parent"] else None
            dep_on = builds[parent_nvr] if parent_nvr in builds else None

            if parent_nvr:
                build = db_event.get_artifact_build_from_event_dependencies(parent_nvr)
                if build:
                    parent_nvr = build[0].rebuilt_nvr
                    dep_on = None

            if "error" in image and image["error"]:
                state_reason = image["error"]
                state = ArtifactBuildState.FAILED.value
            elif dep_on and dep_on.state == ArtifactBuildState.FAILED.value:
                # If this artifact build depends on a build which cannot
                # be built by Freshmaker, mark this one as failed too.
                state_reason = "Cannot build artifact, because its " \
                    "dependency cannot be built."
                state = ArtifactBuildState.FAILED.value
            else:
                state_reason = ""
                state = ArtifactBuildState.PLANNED.value

            image_name = koji.parse_NVR(image.nvr)["name"]
            rebuild_reason = RebuildReason.DIRECTLY_AFFECTED.value
            build = self.record_build(
                event, image_name, ArtifactType.IMAGE,
                dep_on=dep_on,
                state=ArtifactBuildState.PLANNED.value,
                original_nvr=nvr,
                rebuild_reason=rebuild_reason)
            # Set context to particular build so logging shows this build
            # in case of error.
            self.set_context(build)

            build.transition(state, state_reason)

            build.build_args = json.dumps({
                "repository": image["repository"],
                "commit": image["commit"],
                "original_parent": parent_nvr,
                "target": image["target"],
                "branch": image["git_branch"],
                "arches": image["arches"],
                "flatpak": image.get("flatpak", False),
                "isolated": image.get("isolated", True),
            })
            db.session.commit()
        # Reset context to db_event.
        self.set_context(db_event)

    def _get_rpm_nvrs_dict(self, rpm_nvrs):
        rpms_dict = dict()
        for rpm_nvr in rpm_nvrs:
            rpm_info = rpmlib.parse_nvr(rpm_nvr)
            rpm_info.pop("epoch", None)
            rpms_dict.update({rpm_info['name']: rpm_info})
        return rpms_dict
