"""
headless_sim.launch.py

Launches TurtleBot4 simulation server-only (no GUI process).
Uses gz sim -s directly so there is no Ogre/Qt GUI process to crash.
The GUI can connect remotely from a laptop via: gz sim -g

Based on turtlebot4_gz_bringup/turtlebot4_gz.launch.py but with
the GUI launch removed entirely.
"""

import os
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription,
    ExecuteProcess,
    TimerAction,
)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():

    world = LaunchConfiguration("world")
    model = LaunchConfiguration("model")

    declare_world = DeclareLaunchArgument(
        "world",
        default_value="warehouse",
        description="Gazebo world name (without .sdf extension)",
    )

    declare_model = DeclareLaunchArgument(
        "model",
        default_value=os.environ.get("TURTLEBOT4_MODEL", "standard"),
        description="TurtleBot4 model: standard or lite",
    )

    # World SDF path
    world_sdf = PathJoinSubstitution([
        FindPackageShare("turtlebot4_gz_bringup"),
        "worlds",
        [world, ".sdf"],
    ])

    # gz sim server only (-s = server, -r = run immediately, no -g GUI)
    gz_server = ExecuteProcess(
        cmd=["gz", "sim", "-s", "-r", "-v", "3", world_sdf],
        output="screen",
    )

    # Spawn TurtleBot4 into the world (delayed to let server start)
    spawn = TimerAction(
        period=8.0,
        actions=[
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource([
                    PathJoinSubstitution([
                        FindPackageShare("turtlebot4_gz_bringup"),
                        "launch",
                        "turtlebot4_spawn.launch.py",
                    ])
                ]),
                launch_arguments={"model": model}.items(),
            )
        ],
    )

    # ROS-Gazebo bridge (delayed to let robot spawn)
    bridge = TimerAction(
        period=18.0,
        actions=[
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource([
                    PathJoinSubstitution([
                        FindPackageShare("turtlebot4_gz_bringup"),
                        "launch",
                        "ros_gz_bridge.launch.py",
                    ])
                ]),
                launch_arguments={"model": model}.items(),
            )
        ],
    )

    # TurtleBot4 nodes (HMI etc) (delayed to let bridge start)
    tb4_nodes = TimerAction(
        period=24.0,
        actions=[
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource([
                    PathJoinSubstitution([
                        FindPackageShare("turtlebot4_gz_bringup"),
                        "launch",
                        "turtlebot4_nodes.launch.py",
                    ])
                ]),
                launch_arguments={"model": model}.items(),
            )
        ],
    )

    return LaunchDescription([
        declare_world,
        declare_model,
        gz_server,
        spawn,
        bridge,
        tb4_nodes,
    ])