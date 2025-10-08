import io
import os
import base64

import numpy as np
import pandas as pd
from flask import Flask, send_from_directory

import pydicom as dcm
from math import sqrt
from scipy.interpolate import interp1d

import dash
from dash import dcc
from dash import html
from dash import dash_table
import dash_uploader as du
import uuid


import dash_bootstrap_components as dbc
from dash.dependencies import Input, Output, State
import plotly.graph_objects as go

from loguru import logger

from pylinac import PicketFence
from pylinac import Starshot
import pydicom
from datetime import datetime as dt
import time

from PIL import Image

#TPR 483 DATA
trs_ptw_31016 = dict({
    10:   1,
    8:    1, 
    6:    1,
    4:    1.001,
    3:    1.001,
    2.5:  1.001,
    2:    1.004,
    1.5:  1.013,
    1.2:  1.025,
    1.0:  1.039
    })



x = list(trs_ptw_31016.keys())
y = list(trs_ptw_31016.values())
f_ptw_31016 = interp1d(x, y, 'cubic', fill_value='extrapolate')


def check_jaw_tracking(file, beam_number):
    jaw_tracking = 'OFF'
    limiting_devices = file.BeamSequence[beam_number].ControlPointSequence[int(file.BeamSequence[beam_number].NumberOfControlPoints)-1].BeamLimitingDevicePositionSequence
    print(list(limiting_devices))
    for l in range(len(limiting_devices)):
        if limiting_devices[l].RTBeamLimitingDeviceType != 'MLCX':
            jaw_tracking = 'ON'

    return jaw_tracking

def number_of_beams_calculation(file):
    return(int(file.FractionGroupSequence[0].NumberOfBeams))

def select_mlc(control_point):
    for i in range(len(control_point)):
        if control_point[i].RTBeamLimitingDeviceType == 'MLCX':
            mlc_id = i
    return mlc_id

def calculafe_filed_size_varian(file, beam_number, control_point, number_of_leafs,  **kwargs):
    
    leafs = kwargs.pop("leafs", None)
    size = pd.DataFrame()
    
    if leafs == None:
        leafs = range(number_of_leafs)
        logger.info('The machine has '+ str(number_of_leafs)+ ' leaf pairs')
    #field size
    for c in (range(control_point)):
        
        if hasattr(file.BeamSequence[beam_number].ControlPointSequence[c], 'BeamLimitingDevicePositionSequence'):
            mlc_id = select_mlc(file.BeamSequence[beam_number].ControlPointSequence[c].BeamLimitingDevicePositionSequence)
            size.loc[c, 'field_size'] = 0
            for p in leafs:
                leaf_upper_position = file.BeamSequence[beam_number].BeamLimitingDeviceSequence[2].LeafPositionBoundaries[p]
                leaf_lower_position = file.BeamSequence[beam_number].BeamLimitingDeviceSequence[2].LeafPositionBoundaries[p+1]
                
                leaf_left_position = file.BeamSequence[beam_number].ControlPointSequence[c].BeamLimitingDevicePositionSequence[mlc_id].LeafJawPositions[p]
                leaf_right_position = file.BeamSequence[beam_number].ControlPointSequence[c].BeamLimitingDevicePositionSequence[mlc_id].LeafJawPositions[p+number_of_leafs]
                
                
                size_upper_lower = leaf_lower_position - leaf_upper_position
                size_left_right = leaf_right_position - leaf_left_position
                
                #if size_left_right != 0:
                    #print('size_upper_lower' + str(size_upper_lower))
                    #print('size_left_right' + str(size_left_right))
        
                size.loc[c, 'field_size'] = size.loc[c, 'field_size'] + size_upper_lower*size_left_right
            
        elif len(range(control_point)) == 2:
            size.loc[c, 'field_size'] = 0
            for p in leafs:
                leaf_upper_position = file.BeamSequence[beam_number].BeamLimitingDeviceSequence[2].LeafPositionBoundaries[p]
                leaf_lower_position = file.BeamSequence[beam_number].BeamLimitingDeviceSequence[2].LeafPositionBoundaries[p+1]
                leaf_right_position = file.BeamSequence[beam_number].ControlPointSequence[c-1].BeamLimitingDevicePositionSequence[2].LeafJawPositions[p+number_of_leafs]
                leaf_left_position = file.BeamSequence[beam_number].ControlPointSequence[c-1].BeamLimitingDevicePositionSequence[2].LeafJawPositions[p]
    
                size_upper_lower = leaf_lower_position - leaf_upper_position
                size_left_right = leaf_right_position - leaf_left_position
        
                size.loc[c, 'field_size'] = size.loc[c, 'field_size'] + size_upper_lower*size_left_right
        else:
            size.loc[c, 'field_size'] = 'error'
            logger.error('ERROR')
            
                
    
    #field size
    for c in (range(control_point)):
        if c == 0:
            size.loc[c, 'weigh'] = file.BeamSequence[beam_number].ControlPointSequence[c].CumulativeMetersetWeight
        else:
            size.loc[c, 'weigh'] = file.BeamSequence[beam_number].ControlPointSequence[c].CumulativeMetersetWeight - file.BeamSequence[beam_number].ControlPointSequence[c-1].CumulativeMetersetWeight
    
    #calculate mean filed size between control points
    for s in range(len(size)):
        if s == 0:
            size.loc[s, 'mean_size'] = 0
        else:
            size.loc[s, 'mean_size'] = (size.loc[s, 'field_size'] + size.loc[s - 1, 'field_size'])/2
    
            
    return size


external_stylesheets = ['https://codepen.io/chriddyp/pen/bWLwgP.css']

# creating a web server instance
server = Flask(__name__)

# creating app
app = dash.Dash(__name__,
                server=server,
                external_stylesheets=external_stylesheets,
                title='Medphys portal', )

UPLOAD_FOLDER = os.path.join(os.getcwd(),'assets', "Uploads")
REPORTS_FOLDER = os.path.join(os.getcwd(), 'assets', 'Reports')
REPORTS_FOLDER_LINK = os.path.join('assets', 'Reports')

logger.info(f'Upload folder - {UPLOAD_FOLDER}')
du.configure_upload(app, UPLOAD_FOLDER)


style_text = {
    'width': '100px',
    'height': '30px',
    'font-size': 14,
    'textAlign': 'right',
    'margin-top': 0,
    'padding': 5,
    'display': 'inline-block'}

style = {
    'width': '200px',
    'height': '30px',
    'font-size': 14,
    'textAlign': 'center',
    'vertical-align': 'top',
    'display': 'inline-block'}

style_col = {
    'width': '33%',
    'display': 'inline-block'}

logo_path = r'assets/logo.png'


# creating the app layout
app.layout = html.Div([

    dcc.Store(id='memory-output'),
    html.Div([
        dbc.Row([
            dbc.Col([
                html.H1('MEDICAL PHYSICS PORTAL', style={'textAlign': 'left', 'margin-top': 20, 'color': 'white'}, id='title'),
                html.P('Plotly web-tool for pylinac by Yury Kirpichev', style={'testAlign': 'left', 'color': 'white'}),
                html.Br(),
                html.B('For BOCOC usage only', style={'textAlign': 'left', 'color': 'tomato'}),
                ], style={ 'width':'85%', 'display': 'inline-block'}),
            dbc.Col(
                html.Img(src=logo_path, style={'width':'90%', 'text-align': 'right', 'max-width':150, 'max-height':150, 'horisontal-align': 'right','margin-top': 0,},),
                style={'width':'150', 'display': 'inline-block'}),
        ], style={'margin-bottom': 5, 'margin-left': 100}),
        html.Br(),

        
    ], style={'backgroundColor': '#061c42'}),


    html.Br(),
    # creating line with parameters
    dbc.Row([
        html.Strong('Type: ', style=style_text),
        dcc.Dropdown(
            id='type',
            options=['PicketFence', 'Star', 'EffectiveFS', 'WL MultiMet'],
            value='PicketFence',
            style=style
        ),
#       html.Strong('Chamber: ', style=style_text),
#        dcc.Dropdown(
#            id='Chamber',
#            options=['PinPoint 3D 31016'],
#            value='PinPoint 3D 31016',
#            style=style),
#        html.Strong('First leaf: ', style=style_text, id='show-dots-text'),
#        dcc.Input(
#            id='first_leaf',
#            type="number",
#            value=0,
#            style=style,
#            ),
#        html.Strong('Last leaf: ', id='show-cutoff-text', style=style_text),
#        dcc.Input(
#            id='last leaf',
#            type="number",
#            value=60,
#            style=style),'''
    ],
        style={'height': '30px', 'width': '100%', }),
    html.Br(style={'height': 2}),
    # uploading field
    du.Upload(
        text='Drag and Drop files here',
        text_completed='Completed: ',
        pause_button=False,
        cancel_button=True,
        max_file_size=13800,  # 1800 Mb
        filetypes=['dcm'],
        id='upload-files-div',
        max_files=20,
        #upload_id=uuid.uuid1(),
        ),

    html.Button('Analyze', id='submit-val', n_clicks=0),
    # place for the output
    dcc.Loading(html.Div(id='output-data-upload')),
])

#Star Analyzation
def analise_star(upload_id, fileNames):
    
    #fileNames = os.listdir(os.path.join(UPLOAD_FOLDER, upload_id))
    fullFileNames = [os.path.join(os.path.join(UPLOAD_FOLDER, upload_id), f) for f in fileNames]
    logger.info(f'file names = {fullFileNames}')
    star = Starshot.from_multiple_images(fullFileNames)
    #star = Starshot.from_demo_image()
    logger.info(f'Star Test has been successfully strarted')
    try:
        star.analyze(radius=0.5, tolerance=0.8)
    except Exception as e:
        logger.error(f'Error at star.analyze: {e}')
    logger.info(f'Star Test has been successfully analyzed. Results: {star.results()}')
    try:
        machine = np.unique([pydicom.dcmread(f, stop_before_pixels = True, force=True).RadiationMachineName for f in fullFileNames])
        if len(machine) == 1:
            machine = machine[0]
        logger.info(f'Machine: {machine}')

        date =np.unique([pydicom.dcmread(f, stop_before_pixels = True, force=True).ContentDate for f in fullFileNames])
        if len(date) == 1:
            date = date[0]
        logger.info(f'Data: {date}')

        time =np.unique([pydicom.dcmread(f, stop_before_pixels = True, force=True).InstanceCreationTime for f in fullFileNames])
        if len(time) == 1:
            time = time[0]
        logger.info(f'Time: {time}')
 
        gantry_angle =np.unique([pydicom.dcmread(f, stop_before_pixels = True, force=True).GantryAngle for f in fullFileNames])
        if len(gantry_angle) == 1:
            gantry_angle = gantry_angle[0]
        logger.info(f'Gantry Angle: {gantry_angle}')

        export_text = html.Div([
            html.P(f'Machine: {machine}'),
            html.P(f'Irradiation datetime: {date} {time}'),
            html.P(f'Gantry Angle (°): {gantry_angle:.3f}'),
            html.P(f'Tolerance: {star.results_data().tolerance_mm}'),
            html.P(f'Passed: {star.results_data().passed}'),
            html.P(f'Minimum circle diameter: {star.results_data().circle_diameter_mm:.3f} mm'),
            html.P(f'Circle center: {star.results_data().circle_center_x_y[0]:.1f}, {star.results_data().circle_center_x_y[1]:.1f}'),
            ])

        try:
            fig = star.plotly_analyzed_images(show=False, show_colorbar=False, show_legend=False)
        
            fig1 = fig['Image']
            fig1.update_layout(
                margin=dict(
                l=0,
                r=0,
                b=0,
                t=50,
                pad=4),
                )

            fig2 = fig['Wobble']
            fig2.update_layout(
                margin=dict(
                    l=0,
                    r=0,
                    b=0,
                    t=50,
                    pad=4),
                )
        except Exception as e:
            logger.info(f'plotly image failed with error: {e}')
            fig1 = go.Figure()
            fig2 = go.Figure()

        children = html.Div([
            html.H3('Star Test Results:', style={'textAlign':'center'}),
            dbc.Row([
                dbc.Col(html.P(export_text), style=style_col), 
                dbc.Col(dcc.Graph(figure=fig1), style=style_col),
                dbc.Col(dcc.Graph(figure=fig2), style=style_col)]),
        ])
        logger.info(f'Star test analysed sucsesfully')
        logger.info(export_text)
    
    except Exception as e:
        logger.error(f'Error - {e}')
        children = html.Div()

    for f in fullFileNames:
        os.remove(f)
        logger.info(f'Startest files have been deleted')
    return children

#Picket Fence analyzation
def analise_picket_fence(upload_id, fileNames):
    file_path = os.path.join(UPLOAD_FOLDER, upload_id, fileNames[0])
    try:
        logger.info('Picket Fence Analysiation Started')
        timestamp = str(dt.now())
        pf = PicketFence(file_path)
        dcm = pydicom.dcmread(file_path)
        pf.analyze(tolerance=0.5, action_tolerance=0.4, separate_leaves=False,)
        #logger.info(f'Picket Fence Analized Succesuffly results: {pf.results_data()}')

        report_name = f'PF {dcm.RadiationMachineName} {dcm.ContentDate} {dcm.InstanceCreationTime}.pdf' 
        report_path = os.path.join(REPORTS_FOLDER, report_name)
        report_path_link = os.path.join(REPORTS_FOLDER_LINK, report_name)
        pf.publish_pdf(filename = report_path)
        pf_passed = pf.results_data().passed

        if pf_passed:
            failing_leaves = html.P('')
        else:
            failing_leaves = html.B(f'Failing leaves: {pf.results_data().failed_leaves}', style={'color':'tomato'})

        export_text = html.Div([
            html.P(f'Machine: {dcm.RadiationMachineName}'),
            html.P(f'Irradiation datetime: {dcm.ContentDate} {dcm.InstanceCreationTime}'),
            html.P(f'Gantry Angle (°): {dcm.GantryAngle:.2f}'),
            html.P(f'Collimator Angle (°): {dcm.BeamLimitingDeviceAngle:.2f}'),
            html.P(f'Tolerance (mm): {pf.results_data().tolerance_mm:.3f}'),
            html.P(f'Leaves passing (%): {pf.results_data().percent_leaves_passing:.3f}'),
            failing_leaves,
            html.P(f'Absolute median error (mm): {pf.results_data().absolute_median_error_mm:.3f}'),
            html.P(f'Mean picket spacing (mm): {pf.results_data().mean_picket_spacing_mm:.3f}'),
            html.P(f'Picket offsets from CAX (mm):'),
            html.P(f'{[round(v, 1) for v in pf.results_data().offsets_from_cax_mm]}'),
            html.P(f'Max Error (mm): {pf.results_data().max_error_mm:.3f} on Picket: {pf.results_data().max_error_picket}, Leaf: {pf.results_data().max_error_leaf}'),
            html.P(f'MLC Skew (°): {pf.results_data().mlc_skew:.3f}'),
            html.A('Download report', href=report_path_link, download = report_name, target= '_blank')

            ], style={'padding': 25})

        try:
            fig = pf.plotly_analyzed_images(show=False, show_colorbar=False, show_legend=False)
        
            fig1 = fig['Picket Fence']
            fig1.update_layout(
                margin=dict(
                l=0,
                r=0,
                b=0,
                t=50,
                pad=4),
                )
            fig2 = fig['Histogram']
            fig2.update_layout(
                margin=dict(
                    l=0,
                    r=0,
                    b=0,
                    t=50,
                    pad=4),
                )
        except Exception as e:
            logger.error(f'plotly image failed with error: {e}')
            image_name = os.path.join(UPLOAD_FOLDER, upload_id,'pf_image.png')
            hist_name = os.path.join(UPLOAD_FOLDER, upload_id, 'hist_name.png')

            pf.save_analyzed_image(image_name, pad_inches=0,  bbox_inches='tight')
            pf.save_histogram(hist_name)
            fig_image = Image.open(image_name)
            fig_hist = Image.open(hist_name)

            os.remove(hist_name)
            os.remove(image_name)

            logger.info(f'Hist size: {fig_hist.size}')
            fig1 = go.Figure()
            fig1.add_layout_image(
                dict(
                    source=fig_image,
                    xref="x",
                    yref="y",
                    x=0,
                    y=4,    
                    sizex=4,
                    sizey=4,
                    layer="below"
                )
            )

            height = 600
            width = height*fig_image.size[0]/fig_image.size[1]

            fig1.update_layout(yaxis_range=[0,4], xaxis_range=[0,4], width=width, height=height, plot_bgcolor='white')
            fig1.update_xaxes(showgrid=False, showticklabels=False)
            fig1.update_yaxes(showgrid=False, showticklabels=False)

            fig2 = go.Figure()
            fig2.add_layout_image(
                dict(
                    source=fig_hist,
                    xref="x",
                    yref="y",
                    x=0,
                    y=4,    
                    sizex=4,
                    sizey=4,
                    layer="below"
                )
            )
            height = 600
            width = height*fig_hist.size[0]/fig_hist.size[1]
            fig2.update_layout(yaxis_range=[0,4], xaxis_range=[0,4], width=width, height=height, plot_bgcolor='white')
            fig2.update_xaxes(showgrid=False, showticklabels=False)
            fig2.update_yaxes(showgrid=False, showticklabels=False)


        logger.info(f'Picket Fence has been done')
        
        children = html.Div([
            html.H3('Picket Fence Results:', style={'textAlign':'center'}),
            dbc.Row([
                dbc.Col(html.P(export_text), style=style_col), 
                dbc.Col(dcc.Graph(figure=fig1), style=style_col), 
                dbc.Col(dcc.Graph(figure=fig2), style=style_col)
                ])
            ])
    except Exception as e:
        logger.error(e)
        children = html.Div(e)
    os.remove(file_path)
    logger.info(f'Picket Fence file has been deleted')
    return children
def parse_contents_effectiveFS(upload_id, fileNames):
    logger.info(f'Effective field size has been started, filename = {fileNames}')
    file_path = os.path.join(UPLOAD_FOLDER, upload_id, fileNames[0])
    try:
        file = dcm.dcmread(file_path, force=True)
        leafs= range(0,60)
        df = pd.DataFrame()
        text = []
        
        file_type = file.Modality
        if file_type == 'RTPLAN':
            try:
                plan_name = file.RTPlanLabel
            except Exception:
                plan_name = '-' 
        
            try:
                plan_patient_name = file.PatientName 
            except Exception:
                plan_patient_name ='-'
    
            try:    
                plan_date = file.InstanceCreationDate  
            except Exception:
                plan_date = '-'
        
            try:
                plan_time = file.InstanceCreationTime
            except Exception:
                plan_time = '-'
    
            try:
                plan_vendor = file.Manufacturer
            except Exception:    
                plan_vendor = '-'
    
            if plan_vendor == 'Varian Medical Systems':
                number_of_beams = number_of_beams_calculation(file)

                for n in range(number_of_beams):
                    plan_machime_name = file.BeamSequence[n].TreatmentMachineName  
                    plan_beam_name = file.BeamSequence[n].BeamName
                    plan_beam_type = file.BeamSequence[n].BeamType
                    try:
                        technique = file.BeamSequence[n].HighDoseTechniqueType
                    except Exception:
                        technique = '-'
                    try:
                        nominal_energy = file.BeamSequence[n].ControlPointSequence[0].NominalBeamEnergy
                    except Exception:
                        nominal_energy = '-'
                    try:
                        fff_mode = file.BeamSequence[n].PrimaryFluenceModeSequence[0].FluenceModeID
                    except Exception as e:
                        fff_mode = 'WFF'
                    try:
                        dose_rate = file.BeamSequence[n].ControlPointSequence[0].DoseRateSet
                    except Exception:
                        dose_rate = '-'
                    try:
                        beam_number = file.BeamSequence[n].BeamNumber
                    except Exception:
                        beam_number = '-'

            
                    if hasattr(file.FractionGroupSequence[0].ReferencedBeamSequence[n], 'BeamDose'):
                        text.append(str('%s beam name: %s ' %(plan_beam_type, plan_beam_name)))
                        text.append(html.Br())
                
                        plan_beam_dose = file.FractionGroupSequence[0].ReferencedBeamSequence[n].BeamDose
                        plan_beam_meterset = file.FractionGroupSequence[0].ReferencedBeamSequence[n].BeamMeterset
            
                        number_of_leafs = file.BeamSequence[n].BeamLimitingDeviceSequence[2].NumberOfLeafJawPairs

                        number_of_control_points = file.BeamSequence[n].NumberOfControlPoints
                        size_control_point = calculafe_filed_size_varian(file, n, number_of_control_points, number_of_leafs, leafs =leafs)
                        #calculate weighted field size
                        size_control_point['weighted_size'] = size_control_point['mean_size']*size_control_point['weigh']

                        median_value = size_control_point['field_size'].median()
                        low_quantile = size_control_point['field_size'].quantile(0.25)
                        high_quantile = size_control_point['field_size'].quantile(0.75)


                        mean_field_size = size_control_point['weighted_size'].sum()

                        jaw_tracking = check_jaw_tracking(file, n)
                        
                        
                        beam_table = pd.DataFrame([{
                            ' ':n+1,
                            'beam number': beam_number,
                        	'beam type': plan_beam_type,
                        	'beam name': plan_beam_name,
                            'linac': plan_machime_name,
                            'technique': technique,
                            'energy': str(nominal_energy) + str(fff_mode),
                            'dose rate': dose_rate,
                            'jaw tracking': jaw_tracking,
                            'median FS': median_value,
                            'near min(25%) FS': f'{low_quantile:.3f}',
                            'near max(75%) FS': f'{high_quantile:.3f}',
                        	'mean FS corrected for the weights, mm^2': "{:10.4f}".format(mean_field_size),
                        	'effective square FS, cm': "{:10.4f}".format(sqrt(mean_field_size/100)),
                        	'correction factor for PTW PinPoint 3D 31016': "{:10.4f}".format(f_ptw_31016(sqrt(mean_field_size/100)))}])
                        df = pd.concat([df, beam_table], ignore_index=True)
                        	
                    else:
                        text.append(str('%s beam name: %s has no dose' %(plan_beam_type, plan_beam_name)))
                        text.append(html.Br())
                        
                        beam_table = pd.DataFrame([{
                        	'beam type': plan_beam_type,
                        	'beam name': plan_beam_name,}])
                        df = pd.concat([df, beam_table], ignore_index=True)
            if len(df.energy.unique())> 1:
                energy_style = 'tomato'
            else:
                energy_style = 'white'

            if len(df['dose rate'].unique())> 1:
                dose_rate_style = 'tomato'
            else:
                dose_rate_style = 'white'

            xnew = np.linspace(10, 0, num=101, endpoint=True) 

            fig = go.Figure(     
                data=go.Scatter(x=xnew, y= f_ptw_31016(xnew),))
            fig.update_layout(
                title = 'Correction factor for PTW PinPoint 3D 31016',
                yaxis_title = 'Correction factor',
                xaxis_title = 'Effective Square field size, cm')

    except Exception as e:
        print(e)
        return html.Div([
            'There was an error processing this file.' + str(e)
        ])

    return html.Div([
        html.P('The %s was successfully uploaded ' %fileNames[0]),
        html.P('Modality is %s.' %file.Modality),
        html.P('Patient id is %s.' %file.PatientID),
        html.P('Plan  %s has beams :%s ' %(plan_name, number_of_beams)),
        html.Div([dash_table.DataTable(
            data=df.to_dict('records'),
            columns=[{'name':i, 'id':i} for i in df.columns],
            export_format='xlsx',
            style_cell_conditional = [
                {
                    'if': {'column_id': c},
                    'textAlign': 'center'
                } for c in df.columns
            ],
            style_data_conditional = 
            [
                {
                    'if': {
                        'filter_query': '{correction factor for PTW PinPoint 3D 31016} >1.049',
                        'column_id': 'correction factor for PTW PinPoint 3D 31016'
                    },
                    'color': 'tomato',
                    'fontWeight': 'bold',
                },
                {
                    'if': {
                        'column_id': 'correction factor for PTW PinPoint 3D 31016'
                    },
                    'fontSize': '20',
                    'fontWeight': 'bold',
                },
                {
                    'if': {
                        'filter_query': '{jaw tracking} = "ON" && {effective square filed size, cm} < 4',
                        'column_id': 'jaw tracking',
                    },
                    'color': 'tomato',
                    'fontWeight': 'bold',
                },
                {
                    'if': {
                        'filter_query': '{jaw tracking} = "OFF" && {effective square filed size, cm} > 4',
                        'column_id': 'jaw tracking',
                    },
                    'color': 'tomato',
                    'fontWeight': 'bold',
                },
                {
                    'if': {'column_id': 'energy'},
                    'backgroundColor': energy_style
                },
                {
                    'if': {'column_id': 'dose rate'},
                    'backgroundColor': dose_rate_style
                }
                ]
        )]),
        dcc.Graph(figure=fig),
        #html.P(text),
        html.Hr(),  # horizontal line
    ])

#@server.route('/Download/<path:path>')
#def download(path):
#    return send_from_directory(REPORTS_FOLDER, path, as_attachment=True)

@app.callback(Output('output-data-upload', 'children'),
    [Input('type', 'value'), 
     Input('upload-files-div', 'isCompleted'),
     Input('submit-val', 'n_clicks'),],
    [State('upload-files-div', 'fileNames'), 
     State('upload-files-div', 'upload_id')])
def update_output(type_selected, isCompleted, n_clicks, fileNames, upload_id):
    logger.info(f'Selected type - {type_selected}')
    logger.info(f'Upload ID - {upload_id}')
    logger.info(f'Upload Folder - {UPLOAD_FOLDER}')
    if type_selected == 'EffectiveFS':
        if isCompleted and n_clicks != 0:
            children = parse_contents_effectiveFS(upload_id, fileNames)
        else:
            children = [html.Div(f'Upload a plan for analysation')]
        return children
    elif type_selected == 'Star':
        logger.info(f'Star analysation has been started')
        if isCompleted and n_clicks != 0:
            logger.info(f'StarTest upload_id: {upload_id}')
            logger.info(f'StarTest fileNames: {fileNames}')
            logger.info(f'button clicked {n_clicks} times')

            try:
                children = analise_star(upload_id = upload_id, fileNames = fileNames)
               
            except Exception as e:
                children = [html.Div(f'Error: {e}')]
        else:
            children = [html.Div(f'Upload images for Starshot evaluation')]
        return children
    elif type_selected == 'PicketFence':
        logger.info(f'PicketFence analysation has been started')
        if isCompleted and n_clicks != 0:
            logger.info(f'Upload ID: {upload_id}, fileNames: {fileNames}')
            if len(fileNames)!=1:
                return html.Div(f'Upload only one file for PicketFence analysation') 
            children = analise_picket_fence(upload_id = upload_id, fileNames = fileNames)
        else:
            children = html.Div(f'Upload file for PicketFence analysation')
        return children
    elif type_selected == 'WL MultiMet':
        logger.info(f'WL test')
        children = html.Div(f'WL test is under progress, buy @yukirpichev a beer to make him work faster')
        return children
    else:
        children = html.Div(f'Select a test type')
        return children
        
if __name__ == '__main__':
    app.run_server(debug=False, host = '0.0.0.0', port=8050)

