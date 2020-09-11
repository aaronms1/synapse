# -*- coding: utf-8 -*-
# Copyright 2019 The Matrix.org Foundation C.I.C.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from synapse.events import EventBase
from synapse.events.snapshot import EventContext
from synapse.types import Requester, StateMap


class PublicRoomsManager:
    def __init__(self, hs):
        self._store = hs.get_datastore()

    async def room_is_in_public_directory(self, room_id: str) -> bool:
        """Checks whether a room is in the public rooms directory.

        Args:
            room_id: The ID of the room.

        Returns:
            Whether the room is in the public rooms directory.
        """
        return await self._store.get_room_is_public(room_id)

    async def add_room_to_public_directory(self, room_id: str) -> None:
        """Publishes a room to the public rooms directory.

        Args:
            room_id: The ID of the room.
        """
        await self._store.set_room_is_public(room_id, True)

    async def remove_room_from_public_directory(self, room_id: str) -> None:
        """Removes a room from the public rooms directory.

        Args:
            room_id: The ID of the room.
        """
        await self._store.set_room_is_public(room_id, False)


class ThirdPartyEventRules:
    """Allows server admins to provide a Python module implementing an extra
    set of rules to apply when processing events.

    This is designed to help admins of closed federations with enforcing custom
    behaviours.
    """

    def __init__(self, hs):
        self.third_party_rules = None

        self.store = hs.get_datastore()

        module = None
        config = None
        if hs.config.third_party_event_rules:
            module, config = hs.config.third_party_event_rules

        if module is not None:
            self.third_party_rules = module(
                config=config,
                http_client=hs.get_simple_http_client(),
                public_room_manager=PublicRoomsManager(hs),
            )

    async def check_event_allowed(
        self, event: EventBase, context: EventContext
    ) -> bool:
        """Check if a provided event should be allowed in the given context.

        Args:
            event: The event to be checked.
            context: The context of the event.

        Returns:
            True if the event should be allowed, False if not.
        """
        if self.third_party_rules is None:
            return True

        prev_state_ids = await context.get_prev_state_ids()

        # Retrieve the state events from the database.
        state_events = {}
        for key, event_id in prev_state_ids.items():
            state_events[key] = await self.store.get_event(event_id, allow_none=True)

        ret = await self.third_party_rules.check_event_allowed(event, state_events)
        return ret

    async def on_create_room(
        self, requester: Requester, config: dict, is_requester_admin: bool
    ) -> bool:
        """Intercept requests to create room to allow, deny or update the
        request config.

        Args:
            requester
            config: The creation config from the client.
            is_requester_admin: If the requester is an admin

        Returns:
            Whether room creation is allowed or denied.
        """

        if self.third_party_rules is None:
            return True

        ret = await self.third_party_rules.on_create_room(
            requester, config, is_requester_admin
        )
        return ret

    async def check_threepid_can_be_invited(
        self, medium: str, address: str, room_id: str
    ) -> bool:
        """Check if a provided 3PID can be invited in the given room.

        Args:
            medium: The 3PID's medium.
            address: The 3PID's address.
            room_id: The room we want to invite the threepid to.

        Returns:
            True if the 3PID can be invited, False if not.
        """

        if self.third_party_rules is None:
            return True

        state_events = await self._get_state_events_dict_for_room(room_id)

        ret = await self.third_party_rules.check_threepid_can_be_invited(
            medium, address, state_events
        )
        return ret

    async def check_room_can_be_added_to_public_rooms_directory(
        self, room_id: str
    ) -> bool:
        """Check if a room is allowed to be published to the public rooms directory.

        Args:
            room_id: The ID of the room.

        Returns:
            Whether the room is allowed to be published to the public rooms directory.
        """
        if self.third_party_rules is None:
            return True

        state_events = await self._get_state_events_dict_for_room(room_id)

        return await self.third_party_rules.check_room_can_be_added_to_public_rooms_directory(
            room_id, state_events
        )

    async def _get_state_events_dict_for_room(
        self, room_id: str
    ) -> StateMap[EventBase]:
        """Given a room ID, return the state events of that room.

        Args:
            room_id: The ID of the room.

        Returns:
            A dict mapping (event type, state key) to state event.
        """
        state_ids = await self.store.get_filtered_current_state_ids(room_id)
        room_state_events = await self.store.get_events(state_ids.values())

        state_events = {}
        for key, event_id in state_ids.items():
            state_events[key] = room_state_events[event_id]

        return state_events
