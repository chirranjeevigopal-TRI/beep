# Copyright 2019 Toyota Research Institute. All rights reserved.
"""Unit tests related to Generating protocol files"""

import os
import unittest
import json
import numpy as np
import datetime
import shutil
from copy import deepcopy

import pandas as pd
from beep.utils.secrets_manager import event_setup
from beep.protocol import (
    PROCEDURE_TEMPLATE_DIR,
    SCHEDULE_TEMPLATE_DIR,
    BIOLOGIC_TEMPLATE_DIR,
)
from beep.generate_protocol import (
    generate_protocol_files_from_csv,
    convert_velocity_to_power_waveform,
)
from beep.protocol.maccor import Procedure, generate_maccor_waveform_file
from beep.protocol.arbin import Schedule
from beep.protocol.biologic import Settings
from beep.protocol.maccor_to_arbin import ProcedureToSchedule
from monty.tempfile import ScratchDir
from monty.serialization import dumpfn, loadfn
from monty.os import makedirs_p
from beep.utils import os_format, hash_file

import difflib

TEST_DIR = os.path.dirname(__file__)
TEST_FILE_DIR = os.path.join(TEST_DIR, "test_files")


class ProcedureTest(unittest.TestCase):
    def setUp(self):
        # Determine events mode for testing
        self.events_mode = event_setup()

    def test_convert_velocity_to_power_waveform(self):
        velocity_waveform_file = os.path.join(
            TEST_FILE_DIR, "LA4_velocity_waveform.txt"
        )
        df_velocity = pd.read_csv(velocity_waveform_file, sep="\t", header=0)
        df_power = convert_velocity_to_power_waveform(velocity_waveform_file, "mph")
        # Check input and output sizes
        self.assertEqual(len(df_velocity), len(df_power))
        self.assertTrue(any(df_power["power"] < 0))

    def test_generate_maccor_waveform_file_default(self):
        velocity_waveform_file = os.path.join(
            TEST_FILE_DIR, "LA4_velocity_waveform.txt"
        )
        with ScratchDir(".") as scratch_dir:

            df_power = convert_velocity_to_power_waveform(velocity_waveform_file, "mph")
            df_MWF = pd.read_csv(
                generate_maccor_waveform_file(
                    df_power, "test_LA4_waveform", scratch_dir
                ),
                sep="\t",
                header=None,
            )

            # Reference mwf file generated by the cycler for the same power waveform.
            df_MWF_ref = pd.read_csv(
                os.path.join(TEST_FILE_DIR, "LA4_ref_default.mwf"),
                sep="\t",
                header=None,
            )

            self.assertEqual(df_MWF.shape, df_MWF_ref.shape)

            # Check that the fourth column for charge/discharge limit is empty (default setting)
            self.assertTrue(df_MWF.iloc[:, 3].isnull().all())

            # Check that sum of durations equals length of the power timeseries
            self.assertEqual(df_MWF.iloc[:, 5].sum(), len(df_power))

            # Check that charge/discharge steps are identical
            self.assertTrue((df_MWF.iloc[:, 0] == df_MWF_ref.iloc[:, 0]).all())

            # Check that power values are close to each other (col 2)
            relative_differences = np.abs(
                (df_MWF.iloc[:, 2] - df_MWF_ref.iloc[:, 2]) / df_MWF_ref.iloc[:, 2]
            )
            self.assertLessEqual(
                np.mean(relative_differences) * 100, 0.01
            )  # mean percentage error < 0.01%

    def test_generate_maccor_waveform_file_custom(self):
        velocity_waveform_file = os.path.join(
            TEST_FILE_DIR, "US06_velocity_waveform.txt"
        )
        mwf_config = {
            "control_mode": "I",
            "value_scale": 1,
            "charge_limit_mode": "R",
            "charge_limit_value": 2,
            "discharge_limit_mode": "P",
            "discharge_limit_value": 3,
            "charge_end_mode": "V",
            "charge_end_operation": ">=",
            "charge_end_mode_value": 4.2,
            "discharge_end_mode": "V",
            "discharge_end_operation": "<=",
            "discharge_end_mode_value": 3,
            "report_mode": "T",
            "report_value": 10,
            "range": "A",
        }
        with ScratchDir(".") as scratch_dir:
            df_power = convert_velocity_to_power_waveform(velocity_waveform_file, "mph")
            df_MWF = pd.read_csv(
                generate_maccor_waveform_file(
                    df_power, "test_US06_waveform", scratch_dir, mwf_config=mwf_config
                ),
                sep="\t",
                header=None,
            )
            df_MWF_ref = pd.read_csv(
                os.path.join(TEST_FILE_DIR, "US06_reference_custom_settings.mwf"),
                sep="\t",
                header=None,
            )

            # Check dimensions with the reference mwf file
            self.assertEqual(df_MWF.shape, df_MWF_ref.shape)

            # Check that control_mode, charge/discharge state, limit and limit_value columns are identical.
            self.assertTrue(
                (df_MWF.iloc[:, [0, 1, 3, 4]] == df_MWF_ref.iloc[:, [0, 1, 3, 4]])
                .all()
                .all()
            )

            # Check that power values are close to each other (col 2)
            relative_differences = np.abs(
                (df_MWF.iloc[:, 2] - df_MWF_ref.iloc[:, 2]) / df_MWF_ref.iloc[:, 2]
            )
            self.assertLessEqual(
                np.mean(relative_differences) * 100, 0.01
            )  # mean percentage error < 0.01%

    def test_procedure_with_waveform(self):
        maccor_waveform_file = os.path.join(TEST_FILE_DIR, "LA4_8rep_lim.MWF")
        test_file = os.path.join(PROCEDURE_TEMPLATE_DIR, "diagnosticV2.000")
        procedure = Procedure.from_file(test_file)
        rest_step = procedure["MaccorTestProcedure"]["ProcSteps"]["TestStep"][2]
        end_step = procedure["MaccorTestProcedure"]["ProcSteps"]["TestStep"][-1]

        procedure["MaccorTestProcedure"]["ProcSteps"]["TestStep"] = procedure[
            "MaccorTestProcedure"
        ]["ProcSteps"]["TestStep"][:8]
        procedure["MaccorTestProcedure"]["ProcSteps"]["TestStep"][5:9] = deepcopy(
            procedure["MaccorTestProcedure"]["ProcSteps"]["TestStep"][4:8]
        )

        procedure.set("MaccorTestProcedure.ProcSteps.TestStep.5", deepcopy(rest_step))

        procedure.set("MaccorTestProcedure.ProcSteps.TestStep.9", deepcopy(rest_step))

        procedure.set("MaccorTestProcedure.ProcSteps.TestStep.10", deepcopy(end_step))

        procedure.set(
            "MaccorTestProcedure.ProcSteps.TestStep.5.Ends.EndEntry.0.Step", "007"
        )
        procedure.set(
            "MaccorTestProcedure.ProcSteps.TestStep.8.Ends.EndEntry.Step", "010"
        )
        procedure.set(
            "MaccorTestProcedure.ProcSteps.TestStep.9.Ends.EndEntry.0.Step", "011"
        )

        procedure = procedure.insert_maccor_waveform_discharge(6, maccor_waveform_file)
        for step in procedure["MaccorTestProcedure"]["ProcSteps"]["TestStep"]:
            print(step["Ends"])
            if step["StepType"] in ["Charge", "Dischrge", "Rest"]:
                step["Ends"]["EndEntry"][-1]["Step"] = "011"
                step["Ends"]["EndEntry"][-2]["Step"] = "011"

        steps = [
            x["StepType"]
            for x in procedure["MaccorTestProcedure"]["ProcSteps"]["TestStep"]
        ]
        self.assertEqual(
            steps,
            [
                "Rest",
                "Charge",
                "Rest",
                "Do 1",
                "Charge",
                "Rest",
                "FastWave",
                "AdvCycle",
                "Loop 1",
                "Rest",
                "End",
            ],
        )
        self.assertEqual(
            procedure["MaccorTestProcedure"]["ProcSteps"]["TestStep"][5]["Ends"][
                "EndEntry"
            ][0]["Step"],
            "007",
        )
        self.assertEqual(
            procedure["MaccorTestProcedure"]["ProcSteps"]["TestStep"][6]["StepType"],
            "FastWave",
        )

        with ScratchDir(".") as scratch_dir:
            local_name = "test_mwf_LA4_lim.000"
            procedure.to_file(os.path.join(scratch_dir, local_name))
            # Uncomment line below to keep the output in the test file directory
            # shutil.copyfile(os.path.join(scratch_dir, local_name), os.path.join(TEST_FILE_DIR, local_name))

    def test_generate_maccor_waveform_from_power(self):
        power_waveform_file = os.path.join(TEST_FILE_DIR, "LA4_power_profile.csv")
        mwf_config = {
            "control_mode": "P",
            "value_scale": 30,
            "charge_limit_mode": "V",
            "charge_limit_value": 4.2,
            "discharge_limit_mode": "V",
            "discharge_limit_value": 2.7,
            "charge_end_mode": "V",
            "charge_end_operation": ">=",
            "charge_end_mode_value": 4.25,
            "discharge_end_mode": "V",
            "discharge_end_operation": "<=",
            "discharge_end_mode_value": 2.5,
            "report_mode": "T",
            "report_value": 3.0000,
            "range": "A",
        }
        with ScratchDir(".") as scratch_dir:
            waveform_name = "LA4_8rep_lim"
            df_power = pd.read_csv(power_waveform_file)
            df_power = pd.concat(
                [
                    df_power,
                    df_power,
                    df_power,
                    df_power,
                    df_power,
                    df_power,
                    df_power,
                    df_power,
                ]
            )
            df_power.drop(columns=["power"], inplace=True)
            df_power.rename(columns={"power_scaled": "power"}, inplace=True)
            df_MWF = pd.read_csv(
                generate_maccor_waveform_file(
                    df_power, waveform_name, scratch_dir, mwf_config=mwf_config
                ),
                sep="\t",
                header=None,
            )
            sign = df_MWF[0].apply(lambda x: -1 if x is "D" else 1)
            energy = df_MWF[2] * df_MWF[5] * sign
            self.assertLess(df_MWF[5].sum(), 10961)
            self.assertLess(energy.sum(), -20000)
            self.assertGreater(40, df_MWF[2].max())
            self.assertLess(-40, df_MWF[2].min())
            # Uncomment line below to keep the output in the test file directory
            shutil.copyfile(
                os.path.join(scratch_dir, waveform_name + ".MWF"),
                os.path.join(TEST_FILE_DIR, waveform_name + ".MWF"),
            )


class GenerateProcedureTest(unittest.TestCase):
    def setUp(self):
        self.events_mode = event_setup()

    def test_io(self):
        test_file = os.path.join(TEST_FILE_DIR, "xTESLADIAG_000003_CH68.000")
        json_file = os.path.join(TEST_FILE_DIR, "xTESLADIAG_000003_CH68.json")
        test_out = "test1.000"

        procedure = Procedure.from_file(os.path.join(TEST_FILE_DIR, test_file))
        with ScratchDir("."):
            dumpfn(procedure, json_file)
            procedure.to_file(test_out)
            hash1 = hash_file(test_file)
            hash2 = hash_file(test_out)
            if hash1 != hash2:
                original = open(test_file).readlines()
                parsed = open(test_out).readlines()
                self.assertFalse(list(difflib.unified_diff(original, parsed)))
                for line in difflib.unified_diff(original, parsed):
                    self.assertIsNotNone(line)

        test_file = os.path.join(TEST_FILE_DIR, "xTESLADIAG_000004_CH69.000")
        json_file = os.path.join(TEST_FILE_DIR, "xTESLADIAG_000004_CH69.json")
        test_out = "test2.000"

        procedure = Procedure.from_file(os.path.join(TEST_FILE_DIR, test_file))
        with ScratchDir("."):
            dumpfn(procedure, json_file)
            procedure.to_file(test_out)
            hash1 = hash_file(test_file)
            hash2 = hash_file(test_out)
            if hash1 != hash2:
                original = open(test_file).readlines()
                parsed = open(test_out).readlines()
                self.assertFalse(list(difflib.unified_diff(original, parsed)))
                for line in difflib.unified_diff(original, parsed):
                    self.assertIsNotNone(line)

    def test_generate_proc_exp(self):
        test_file = os.path.join(TEST_FILE_DIR, "EXP.000")
        json_file = os.path.join(TEST_FILE_DIR, "EXP.json")
        test_out = "test_EXP.000"
        test_parameters = ["4.2", "2.0C", "2.0C"]
        procedure = Procedure.from_exp(*test_parameters)
        with ScratchDir("."):
            dumpfn(procedure, json_file)
            procedure.to_file(test_out)
            hash1 = hash_file(test_file)
            hash2 = hash_file(test_out)
            if hash1 != hash2:
                original = open(test_file).readlines()
                parsed = open(test_out).readlines()
                self.assertFalse(list(difflib.unified_diff(original, parsed)))
                for line in difflib.unified_diff(original, parsed):
                    self.assertIsNotNone(line)

    def test_missing(self):
        test_parameters = ["EXP", "4.2", "2.0C", "2.0C"]
        template = os.path.join(TEST_FILE_DIR, "EXP_missing.000")
        self.assertRaises(
            UnboundLocalError, Procedure.from_exp, *test_parameters[1:] + [template]
        )

    def test_prediag_with_waveform(self):
        maccor_waveform_file = os.path.join(TEST_FILE_DIR, "LA4_8rep_lim.MWF")
        test_file = os.path.join(PROCEDURE_TEMPLATE_DIR, "diagnosticV3.000")
        csv_file = os.path.join(TEST_FILE_DIR, "PredictionDiagnostics_parameters.csv")
        protocol_params_df = pd.read_csv(csv_file)
        index = 1
        protocol_params_df.iloc[
            index, protocol_params_df.columns.get_loc("capacity_nominal")
        ] = 3.71
        protocol_params = protocol_params_df.iloc[index]
        diag_params_df = pd.read_csv(
            os.path.join(PROCEDURE_TEMPLATE_DIR, "PreDiag_parameters - DP.csv")
        )
        diagnostic_params = diag_params_df[
            diag_params_df["diagnostic_parameter_set"]
            == protocol_params["diagnostic_parameter_set"]
        ].squeeze()

        procedure = Procedure.generate_procedure_regcyclev3(index, protocol_params)
        procedure.generate_procedure_diagcyclev3(
            protocol_params["capacity_nominal"], diagnostic_params
        )

        steps = [
            x["StepType"]
            for x in procedure["MaccorTestProcedure"]["ProcSteps"]["TestStep"]
        ]
        print(steps)
        start = 27
        reg_cycle_steps = [
            "Do 1",
            "Charge",
            "Charge",
            "Charge",
            "Rest",
            "Dischrge",
            "Rest",
            "AdvCycle",
            "Loop 1",
        ]
        reg_steps_len = len(reg_cycle_steps)
        self.assertEqual(steps[start : start + reg_steps_len], reg_cycle_steps)
        start = 59
        reg_cycle_steps = [
            "Do 2",
            "Charge",
            "Charge",
            "Charge",
            "Rest",
            "Dischrge",
            "Rest",
            "AdvCycle",
            "Loop 2",
        ]
        reg_steps_len = len(reg_cycle_steps)
        self.assertEqual(steps[start : start + reg_steps_len], reg_cycle_steps)
        print(procedure["MaccorTestProcedure"]["ProcSteps"]["TestStep"][32])
        print(procedure["MaccorTestProcedure"]["ProcSteps"]["TestStep"][64])

        procedure.insert_maccor_waveform_discharge(32, maccor_waveform_file)
        procedure.insert_maccor_waveform_discharge(64, maccor_waveform_file)
        self.assertEqual(
            procedure["MaccorTestProcedure"]["ProcSteps"]["TestStep"][32]["StepType"],
            "FastWave",
        )
        self.assertEqual(
            procedure["MaccorTestProcedure"]["ProcSteps"]["TestStep"][64]["StepType"],
            "FastWave",
        )
        with ScratchDir(".") as scratch_dir:
            driving_test_name = "Drive_test20200716.000"
            procedure.to_file(driving_test_name)
            # Uncomment line below to keep the output in the test file directory
            # shutil.copyfile(os.path.join(scratch_dir, driving_test_name),
            #                 os.path.join(TEST_FILE_DIR, driving_test_name))

    def test_from_csv(self):
        csv_file = os.path.join(TEST_FILE_DIR, "parameter_test.csv")

        # Test basic functionality
        with ScratchDir(".") as scratch_dir:
            makedirs_p(os.path.join(scratch_dir, "procedures"))
            makedirs_p(os.path.join(scratch_dir, "names"))
            new_files, result, message = generate_protocol_files_from_csv(
                csv_file, output_directory=scratch_dir
            )
            self.assertEqual(
                len(os.listdir(os.path.join(scratch_dir, "procedures"))), 3
            )
            self.assertEqual(result, "error")

        # Test avoid overwriting file functionality
        with ScratchDir(".") as scratch_dir:
            makedirs_p(os.path.join(scratch_dir, "procedures"))
            makedirs_p(os.path.join(scratch_dir, "names"))
            dumpfn({"hello": "world"}, os.path.join("procedures", "name_000007.000"))
            new_files, result, message = generate_protocol_files_from_csv(
                csv_file, output_directory=scratch_dir
            )
            post_file = loadfn(os.path.join("procedures", "name_000007.000"))
            self.assertEqual(post_file, {"hello": "world"})
            self.assertEqual(
                len(os.listdir(os.path.join(scratch_dir, "procedures"))), 3
            )
            self.assertEqual(result, "error")
            self.assertEqual(
                message,
                {
                    "comment": "Unable to find template: EXP-D3.000",
                    "error": "Not Found",
                },
            )

    def test_from_csv_2(self):
        csv_file = os.path.join(TEST_FILE_DIR, "PredictionDiagnostics_parameters.csv")

        # Test basic functionality
        with ScratchDir(".") as scratch_dir:
            makedirs_p(os.path.join(scratch_dir, "procedures"))
            makedirs_p(os.path.join(scratch_dir, "names"))
            new_files, result, message = generate_protocol_files_from_csv(
                csv_file, output_directory=scratch_dir
            )
            self.assertEqual(result, "success")
            self.assertEqual(message, {"comment": "Generated 2 protocols", "error": ""})
            self.assertEqual(
                len(os.listdir(os.path.join(scratch_dir, "procedures"))), 2
            )

            original = open(
                os.path.join(PROCEDURE_TEMPLATE_DIR, "diagnosticV2.000")
            ).readlines()
            parsed = open(
                os.path.join(
                    os.path.join(scratch_dir, "procedures"),
                    "PredictionDiagnostics_000000.000",
                )
            ).readlines()
            self.assertFalse(list(difflib.unified_diff(original, parsed)))
            for line in difflib.unified_diff(original, parsed):
                self.assertIsNotNone(line)

            original = open(
                os.path.join(PROCEDURE_TEMPLATE_DIR, "diagnosticV3.000")
            ).readlines()
            parsed = open(
                os.path.join(
                    os.path.join(scratch_dir, "procedures"),
                    "PredictionDiagnostics_000196.000",
                )
            ).readlines()
            diff = list(difflib.unified_diff(original, parsed))
            diff_expected = [
                "--- \n",
                "+++ \n",
                "@@ -27,7 +27,7 @@\n",
                "           <SpecialType> </SpecialType>\n",
                "           <Oper> = </Oper>\n",
                "           <Step>002</Step>\n",
                "-          <Value>03:00:00</Value>\n",
                "+          <Value>03:12:00</Value>\n",
                "         </EndEntry>\n",
                "         <EndEntry>\n",
                "           <EndType>Voltage </EndType>\n",
            ]
            self.assertEqual(diff, diff_expected)
            for line in difflib.unified_diff(original, parsed):
                self.assertIsNotNone(line)

            _, namefile = os.path.split(csv_file)
            namefile = namefile.split("_")[0] + "_names_"
            namefile = (
                namefile + datetime.datetime.now().strftime("%Y%m%d_%H%M") + ".csv"
            )
            names_test = open(os.path.join(scratch_dir, "names", namefile)).readlines()
            self.assertEqual(
                names_test,
                ["PredictionDiagnostics_000000_\n", "PredictionDiagnostics_000196_\n"],
            )

    @unittest.skip
    def test_from_csv_3(self):

        csv_file_list = os.path.join(TEST_FILE_DIR, "PreDiag_parameters - GP.csv")
        makedirs_p(os.path.join(TEST_FILE_DIR, "procedures"))
        makedirs_p(os.path.join(TEST_FILE_DIR, "names"))
        generate_protocol_files_from_csv(csv_file_list, output_directory=TEST_FILE_DIR)
        if os.path.isfile(os.path.join(TEST_FILE_DIR, "procedures", ".DS_Store")):
            os.remove(os.path.join(TEST_FILE_DIR, "procedures", ".DS_Store"))
        self.assertEqual(
            len(os.listdir(os.path.join(TEST_FILE_DIR, "procedures"))), 265
        )

    def test_console_script(self):
        csv_file = os.path.join(TEST_FILE_DIR, "parameter_test.csv")

        # Test script functionality
        with ScratchDir(".") as scratch_dir:
            # Set BEEP_PROCESSING_DIR directory to scratch_dir
            os.environ["BEEP_PROCESSING_DIR"] = os.getcwd()
            procedures_path = os.path.join("data-share", "protocols", "procedures")
            names_path = os.path.join("data-share", "protocols", "names")
            makedirs_p(procedures_path)
            makedirs_p(names_path)

            # Test the script
            json_input = json.dumps({"file_list": [csv_file], "mode": self.events_mode})
            os.system("generate_protocol {}".format(os_format(json_input)))
            self.assertEqual(len(os.listdir(procedures_path)), 3)


class ProcedureToScheduleTest(unittest.TestCase):
    def setUp(self):
        self.events_mode = event_setup()

    def test_single_step_conversion(self):
        procedure = Procedure()

        templates = PROCEDURE_TEMPLATE_DIR

        test_file = "diagnosticV3.000"
        json_file = "test.json"

        proc_dict = procedure.from_file(os.path.join(templates, test_file))
        test_step_dict = proc_dict["MaccorTestProcedure"]["ProcSteps"]["TestStep"]

        converter = ProcedureToSchedule(test_step_dict)
        step_index = 5
        step_name_list, step_flow_ctrl = converter.create_metadata()

        self.assertEqual(step_flow_ctrl[7], "5-reset cycle C/20")
        self.assertEqual(step_flow_ctrl[68], "38-reset cycle")

        step_arbin = converter.compile_to_arbin(
            test_step_dict[step_index], step_index, step_name_list, step_flow_ctrl
        )
        self.assertEqual(step_arbin["m_szLabel"], "6-None")
        self.assertEqual(step_arbin["Limit0"]["m_szGotoStep"], "Next Step")
        self.assertEqual(step_arbin["Limit0"]["Equation0_szLeft"], "PV_CHAN_Voltage")
        self.assertEqual(
            step_arbin["Limit2"]["m_szGotoStep"], "70-These are the 2 reset cycles"
        )

        step_index = 8
        step_arbin = converter.compile_to_arbin(
            test_step_dict[step_index], step_index, step_name_list, step_flow_ctrl
        )

        self.assertEqual(
            step_arbin["Limit0"]["Equation0_szLeft"], "PV_CHAN_CV_Stage_Current"
        )
        self.assertEqual(
            step_arbin["Limit0"]["Equation0_szRight"],
            test_step_dict[step_index]["Ends"]["EndEntry"][0]["Value"],
        )

    def test_serial_conversion(self):
        procedure = Procedure()

        templates = PROCEDURE_TEMPLATE_DIR

        test_file = "diagnosticV3.000"
        json_file = "test.json"

        proc_dict = procedure.from_file(os.path.join(templates, test_file))

        test_step_dict = proc_dict["MaccorTestProcedure"]["ProcSteps"]["TestStep"]

        converter = ProcedureToSchedule(test_step_dict)
        step_name_list, step_flow_ctrl = converter.create_metadata()

        for step_index, step in enumerate(test_step_dict):
            if "Loop" in step["StepType"]:
                print(step_index, step)
            step_arbin = converter.compile_to_arbin(
                test_step_dict[step_index], step_index, step_name_list, step_flow_ctrl
            )
            if "Loop" in step["StepType"]:
                self.assertEqual(step_arbin["m_szStepCtrlType"], "Set Variable(s)")
                self.assertEqual(step_arbin["m_uLimitNum"], "2")
            if step_index == 15:
                self.assertEqual(step_arbin["Limit0"]["m_szGotoStep"], "11-None")
                self.assertEqual(step_arbin["Limit1"]["m_szGotoStep"], "Next Step")

    def test_schedule_creation(self):
        protocol_params_dict = {
         'project_name': ['PreDiag'],
         'seq_num': [100],
         'template': ['diagnosticV3.000'],
         'charge_constant_current_1': [1],
         'charge_percent_limit_1': [30],
         'charge_constant_current_2': [1],
         'charge_cutoff_voltage': [3.6],
         'charge_constant_voltage_time': [30],
         'charge_rest_time': [5],
         'discharge_constant_current': [1],
         'discharge_cutoff_voltage': [3.0],
         'discharge_rest_time': [15],
         'cell_temperature_nominal': [25],
         'cell_type': ['Tesla_Model3_21700'],
         'capacity_nominal': [1.1],
         'diagnostic_type': ['HPPC+RPT'],
         'diagnostic_parameter_set': ['Tesla21700'],
         'diagnostic_start_cycle': [30],
         'diagnostic_interval': [100]
         }
        procedure_to_convert = 'test_procedure.000'
        with ScratchDir('.') as scratch_dir:
            protocol_params_df = pd.DataFrame.from_dict(protocol_params_dict)
            protocol_params = protocol_params_df.iloc[[0]].squeeze()

            diag_params_df = pd.read_csv(os.path.join(PROCEDURE_TEMPLATE_DIR,
                                                      "PreDiag_parameters - DP.csv"))
            diagnostic_params = diag_params_df[diag_params_df['diagnostic_parameter_set'] == 'A123LFP']

            procedure = Procedure.generate_procedure_regcyclev3(0, protocol_params)
            procedure.generate_procedure_diagcyclev3(
                protocol_params["capacity_nominal"], diagnostic_params
            )
            procedure.set_skip_to_end_diagnostic(3.8, 2.0, step_key='070')
            self.assertEqual(procedure['MaccorTestProcedure']['ProcSteps']['TestStep'][0]\
                                 ['Ends']['EndEntry'][1]['Value'], 3.8)
            self.assertEqual(procedure['MaccorTestProcedure']['ProcSteps']['TestStep'][0]\
                                 ['Ends']['EndEntry'][2]['Value'], 2.0)
            procedure.to_file(os.path.join(scratch_dir, procedure_to_convert))

            sdu_test_input = os.path.join(SCHEDULE_TEMPLATE_DIR, '20170630-3_6C_9per_5C.sdu')
            converted_sdu_name = 'schedule_test_20200724.sdu'
            proc_dict = procedure.from_file(os.path.join(scratch_dir, procedure_to_convert))

            sdu_test_output = os.path.join(TEST_FILE_DIR, converted_sdu_name)
            test_step_dict = proc_dict['MaccorTestProcedure']['ProcSteps']['TestStep']

            converter = ProcedureToSchedule(test_step_dict)
            global_min_cur = -2 * 1.5 * protocol_params['capacity_nominal']
            global_max_cur = 2 * 1.5 * protocol_params['capacity_nominal']
            converter.create_sdu(sdu_test_input, sdu_test_output, current_range='Range2',
                                 global_v_range=[2.0, 3.8], global_temp_range=[0, 60],
                                 global_current_range=[global_min_cur, global_max_cur])
            parsed = open(sdu_test_output, encoding='latin-1').readlines()
            self.assertEqual(parsed[328], '[Schedule_Step3_Limit0]\n')
            self.assertEqual(parsed[6557], '[Schedule_UserDefineSafety15]\n')
            schedule = Schedule.from_file(os.path.join(sdu_test_output))
            self.assertEqual(schedule['Schedule']['Step15']['m_uLimitNum'], '2')
            self.assertEqual(schedule['Schedule']['Step14']['m_uLimitNum'], '6')
            self.assertEqual(schedule['Schedule']['m_uStepNum'], '96')
            self.assertEqual(schedule['Schedule']['Step86']['m_szCtrlValue'], '15')
            self.assertEqual(schedule['Schedule']['Step86']['m_szExtCtrlValue1'], '1')
            self.assertEqual(schedule['Schedule']['Step86']['m_szExtCtrlValue2'], '0')
            #
            # shutil.copyfile(os.path.join(TEST_FILE_DIR, converted_sdu_name),
            #                 os.path.join(scratch_dir, converted_sdu_name))


class ArbinScheduleTest(unittest.TestCase):
    def setUp(self):
        self.events_mode = event_setup()

    def test_dict_to_file(self):
        filename = "20170630-3_6C_9per_5C.sdu"
        schedule = Schedule.from_file(os.path.join(SCHEDULE_TEMPLATE_DIR, filename))
        testname = "test1.sdu"
        with ScratchDir("."):
            dumpfn(schedule, "schedule_test.json")
            schedule.to_file(testname)
            hash1 = hash_file(os.path.join(SCHEDULE_TEMPLATE_DIR, filename))
            hash2 = hash_file(testname)
            if hash1 != hash2:
                original = open(
                    os.path.join(SCHEDULE_TEMPLATE_DIR, filename), encoding="latin-1"
                ).read()
                parsed = open(testname, encoding="latin-1").read()
                self.assertFalse(list(difflib.unified_diff(original, parsed)))
                for line in difflib.unified_diff(original, parsed):
                    print(line)

    def test_fastcharge(self):
        filename = "20170630-3_6C_9per_5C.sdu"
        test_file = "test.sdu"
        sdu = Schedule.from_fast_charge(
            1.1 * 3.6, 0.086, 1.1 * 5, os.path.join(SCHEDULE_TEMPLATE_DIR, filename)
        )
        with ScratchDir("."):
            sdu.to_file(test_file)
            hash1 = hash_file(os.path.join(SCHEDULE_TEMPLATE_DIR, filename))
            hash2 = hash_file(test_file)
            if hash1 != hash2:
                original = open(
                    os.path.join(SCHEDULE_TEMPLATE_DIR, filename), encoding="latin-1"
                ).readlines()
                parsed = open(test_file, encoding="latin-1").readlines()
                udiff = list(difflib.unified_diff(original, parsed))
                for line in udiff:
                    print(line)
                self.assertFalse(udiff)


class BiologicSettingsTest(unittest.TestCase):
    def setUp(self):
        self.events_mode = event_setup()

    def test_from_file(self):
        filename = "BCS - 171.64.160.115_Ta19_ourprotocol_gdocSEP2019_CC7.mps"
        bcs = Settings.from_file(os.path.join(BIOLOGIC_TEMPLATE_DIR, filename))
        self.assertEqual(len(bcs["Technique"]["1"]["Step"].keys()), 55)
        self.assertEqual(bcs.get("Technique.1.Step.5.Ns"), "4")
        self.assertEqual(bcs["Technique"]["1"]["Type"], "Modulo Bat")
        self.assertEqual(bcs["Metadata"]["BT-LAB SETTING FILE"], None)
        self.assertEqual(bcs["Metadata"]["line3"], "blank")
        self.assertEqual(bcs["Metadata"]["Device"], "BCS-805")

    def test_to_file(self):
        filename = "BCS - 171.64.160.115_Ta19_ourprotocol_gdocSEP2019_CC7.mps"
        bcs = Settings.from_file(os.path.join(BIOLOGIC_TEMPLATE_DIR, filename))
        test_name = "test.mps"
        with ScratchDir("."):
            bcs.to_file(test_name)
            original = open(
                os.path.join(BIOLOGIC_TEMPLATE_DIR, filename), encoding="ISO-8859-1"
            ).readlines()
            parsed = open(test_name, encoding="ISO-8859-1").readlines()
            udiff = list(difflib.unified_diff(original, parsed))
            for line in udiff:
                print(line)
            self.assertFalse(udiff)

    def test_insertion(self):
        filename = "BCS - 171.64.160.115_Ta19_ourprotocol_gdocSEP2019_CC7.mps"
        bcs = Settings.from_file(os.path.join(BIOLOGIC_TEMPLATE_DIR, filename))
        value = "{:.3f}".format(5)
        bcs.set("Technique.1.Step.3.ctrl1_val", value)
        self.assertEqual(bcs.get("Technique.1.Step.3.ctrl1_val"), "5.000")
        test_name = "test.mps"
        with ScratchDir("."):
            bcs.to_file(test_name)
            original = open(
                os.path.join(BIOLOGIC_TEMPLATE_DIR, filename), encoding="ISO-8859-1"
            ).readlines()
            parsed = open(test_name, encoding="ISO-8859-1").readlines()
            udiff = list(difflib.unified_diff(original, parsed))
            for line in udiff:
                print(line)
            self.assertTrue(udiff)  # Assert that file is not the same as the template

    def test_parameterization(self):
        filename = "formationV1.mps"
        bcs = Settings.from_file(os.path.join(BIOLOGIC_TEMPLATE_DIR, filename))
        protocol_params_df = pd.read_csv(os.path.join(TEST_FILE_DIR,
                                                      "data-share",
                                                      "raw",
                                                      "parameters",
                                                      "Form_parameters - GP.csv"))
        test_name = "test.mps"
        with ScratchDir(".") as scratch_dir:
            makedirs_p(os.path.join(scratch_dir, "settings"))
            for index, protocol_params in protocol_params_df.iterrows():
                template = protocol_params["template"]
                filename_prefix = "_".join(
                    [
                        protocol_params["project_name"],
                        "{:06d}".format(protocol_params["seq_num"]),
                    ]
                )
                if template == "formationV1.mps":
                    bcs = Settings.from_file(os.path.join(BIOLOGIC_TEMPLATE_DIR, filename))

                    self.assertEqual(bcs.get("Metadata.Cycle Definition"), "Charge/Discharge alternance")
                    bcs = bcs.formation_protocol_bcs(protocol_params)
                    self.assertEqual(bcs.get("Technique.1.Step.2.ctrl1_val"), float(round(0.2 * 0.1, 3)))
                    self.assertEqual(bcs.get("Technique.1.Step.3.lim1_value"), float(round(60, 3)))
                    self.assertEqual(bcs.get("Technique.1.Step.4.lim1_value"), float(round(30, 3)))
                    self.assertEqual(bcs.get("Technique.1.Step.5.ctrl1_val"), float(round(0.2 * 0.2, 3)))
                    self.assertEqual(bcs.get("Technique.1.Step.6.lim1_value"), float(round(30, 3)))
                    self.assertEqual(bcs.get("Technique.1.Step.7.lim1_value"), float(round(30, 3)))
                    self.assertEqual(bcs.get("Technique.1.Step.8.ctrl1_val"), float(round(0.2 * 0.2, 3)))
                    self.assertEqual(bcs.get("Technique.1.Step.8.lim1_value"), float(round(3.0, 3)))
                    self.assertEqual(bcs.get("Technique.1.Step.9.ctrl1_val"), float(round(0.2 * 0.5, 3)))
                    self.assertEqual(bcs.get("Technique.1.Step.10.lim1_value"), float(round(3.9, 3)))
                    self.assertEqual(bcs.get("Technique.1.Step.11.ctrl_repeat"), int(1))
                    self.assertEqual(bcs.get("Technique.1.Step.12.ctrl1_val"), float(round(0.2 * 1, 3)))
                    self.assertEqual(bcs.get("Technique.1.Step.13.lim1_value"), float(round(3.5, 3)))
                    self.assertEqual(bcs.get("Technique.1.Step.14.ctrl1_val"), float(round(3.5, 3)))

                test_name = "{}.mps".format(filename_prefix)
                test_name = os.path.join(scratch_dir, "settings", test_name)
                bcs.to_file(test_name)
            self.assertEqual(len(os.listdir(os.path.join(scratch_dir, "settings"))), 16)
            original = open(
                os.path.join(BIOLOGIC_TEMPLATE_DIR, filename), encoding="ISO-8859-1"
            ).readlines()
            parsed = open(test_name, encoding="ISO-8859-1").readlines()
            udiff = list(difflib.unified_diff(original, parsed))
            for line in udiff:
                print(line)
            self.assertTrue(udiff)  # Assert that last file is not the same as the template
