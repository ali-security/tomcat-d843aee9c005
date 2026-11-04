#!/bin/sh

# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# after_script helper: Travis archives job logs asynchronously, so a log read
# right after the job ends can stop before the test summary. Keep the job open
# (printing a heartbeat, so Travis's 10-minute no-output watchdog never fires)
# until this job's public log contains the per-connector totals that
# .travis/testSummary.py prints last, capped at 15 minutes. after_script cannot
# change the build result.
MAX=900
elapsed=0
URL="https://api.travis-ci.com/v3/job/${TRAVIS_JOB_ID}/log.txt"
while [ "$elapsed" -lt "$MAX" ]; do
    if curl -fsSL "$URL" 2>/dev/null | grep -q 'TOTAL \['; then
        echo "wait-for-log: test summary archived after ${elapsed}s"
        exit 0
    fi
    echo "wait-for-log: waiting for log archive... (${elapsed}s)"
    sleep 20
    elapsed=$((elapsed + 20))
done
echo "wait-for-log: gave up after ${MAX}s"
